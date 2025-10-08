import io
import time
import difflib
import inspect
import warnings
import contextlib
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from talvez import just, nothing

Outcome = str  # "OK! Success" or "NOK! Failure"

def _now_iso() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

def _safe_repr(obj: Any, limit: int = 2000) -> str:
    try:
        s = repr(obj)
    except Exception as e:  # noqa: BLE001
        s = f"<unreprable: {e}>"
    if len(s) > limit:
        return s[:limit] + " ... [truncated]"
    return s

def _format_log_line(ok: bool, fn_label: str, started_at: str, elapsed_s: float) -> str:
    status = "OK" if ok else "NOK"
    return f"{status} `{fn_label}` at {started_at} ({elapsed_s:.3f}s)"

def _summarize_diff(a: str, b: str) -> str:
    # Simple summary based on SequenceMatcher opcodes
    sm = difflib.SequenceMatcher(None, a, b)
    ins = dels = eq = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            ins += (j2 - j1)
        elif tag == "delete":
            dels += (i2 - i1)
        elif tag == "replace":
            dels += (i2 - i1)
            ins += (j2 - j1)
        elif tag == "equal":
            eq += (i2 - i1)
    return f"Found differences: {ins} insertions, {dels} deletions, {eq} matches (char units)"

class Chronicle:
    """
    A container for the result of a recorded function and its composed logs.
    The `value` is a Maybe (from talvez): either Just(value) or Nothing().
    """

    def __init__(
        self,
        value: Any,
        log_df: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[str]] = None,
    ) -> None:
        self.value = value               # Maybe
        self.log_df = log_df or []       # list of dict rows
        self._lines = lines or []        # printable log lines

    def __repr__(self) -> str:
        ok = self.is_ok()
        header = "OK! Value computed successfully:" if ok else "NOK! Value computed unsuccessfully:"
        maybe_str = _safe_repr(self.value)
        body = f"Just({_safe_repr(self.value.value)})" if ok else "Nothing"
        # Mirror chronicler's two-part print: value then hint
        return (
            f"{header}\n---------------\n{body}\n\n---------------\n"
            "This is an object of type `chronicle`.\n"
            "Retrieve the value of this object with unveil(.c, \"value\").\n"
            "To read the log of this object, call read_log(.c).\n"
        )

    def is_ok(self) -> bool:
        return hasattr(self.value, "is_just") and self.value.is_just

    def read_log(self) -> List[str]:
        return list(self._lines)

    def bind_record(self, rfunc: "RecordedFunction", *args, **kwargs) -> "Chronicle":
        """
        Chain another recorded function, composing logs. If current value is Nothing,
        short-circuit and append a NOK log entry for rfunc without executing it.
        """
        # Determine next op number
        next_op = len(self.log_df) + 1

        if not self.is_ok():
            # Short-circuit: add NOK entry explaining propagation
            fn_label = rfunc.fn_label
            started_at = _now_iso()
            line = _format_log_line(False, fn_label, started_at, 0.0)
            new_row = {
                "ops_number": next_op,
                "outcome": "NOK! Failure",
                "function": fn_label,
                "message": "Short-circuited due to Nothing",
                "start_time": started_at,
                "end_time": started_at,
                "run_time": 0.0,
                "g": None,
                "diff_obj": None,
                "lag_outcome": self.log_df[-1]["outcome"] if self.log_df else None,
            }
            out = Chronicle(value=self.value, log_df=self.log_df + [new_row], lines=self._lines + [line])
            return out

        # Execute next with underlying value as first argument
        base_val = self.value.value
        next_ch = rfunc(base_val, *args, **kwargs)

        # Renumber ops in next_ch and compose
        renumbered = []
        for i, row in enumerate(next_ch.log_df, start=1):
            nr = dict(row)
            nr["ops_number"] = next_op - 1 + i
            nr["lag_outcome"] = self.log_df[-1]["outcome"] if (self.log_df and i == 1) else (renumbered[-1]["outcome"] if renumbered else None)
            renumbered.append(nr)

        out = Chronicle(
            value=next_ch.value,
            log_df=self.log_df + renumbered,
            lines=self._lines + next_ch.read_log(),
        )
        return out

def unveil(c: Chronicle, what: str = "value") -> Any:
    """
    unveil(chronicle, "value") -> underlying value or None
    unveil(chronicle, "log_df") -> list of dicts with detailed log rows
    unveil(chronicle, "lines") -> printable log lines
    """
    if what == "value":
        return c.value.value if hasattr(c.value, "is_just") and c.value.is_just else None
    elif what == "log_df":
        return c.log_df
    elif what == "lines":
        return c.read_log()
    else:
        raise ValueError('what must be one of: "value", "log_df", "lines"')

def read_log(c: Chronicle) -> List[str]:
    return c.read_log()

def check_g(c: Chronicle) -> List[Dict[str, Any]]:
    """
    Return a compact view of inspector outputs across steps.
    """
    return [
        {"ops_number": row.get("ops_number"), "function": row.get("function"), "g": row.get("g")}
        for row in c.log_df
    ]

def check_diff(c: Chronicle) -> List[Dict[str, Any]]:
    """
    Return the diff objects recorded at each step.
    """
    return [
        {"ops_number": row.get("ops_number"), "function": row.get("function"), "diff_obj": row.get("diff_obj")}
        for row in c.log_df
    ]

class RecordedFunction:
    def __init__(
        self,
        func: Callable[..., Any],
        strict: int = 1,
        g: Optional[Callable[[Any], Any]] = None,
        diff: str = "none",  # "none" | "summary" | "full"
        name: Optional[str] = None,
    ) -> None:
        self.func = func
        self.strict = strict
        self.g = g
        if diff not in ("none", "summary", "full"):
            raise ValueError('diff must be one of: "none", "summary", "full"')
        self.diff = diff
        self.fn_label = name or getattr(func, "__name__", "<anonymous>")

    def __call__(self, *args, **kwargs) -> Chronicle:
        # Prepare inputs and timing
        started_at = _now_iso()
        t0 = time.perf_counter()
        input_repr = _safe_repr({"args": args, "kwargs": kwargs})

        # Capture warnings and stdout "messages"
        warning_records: List[warnings.WarningMessage] = []
        stdout_buf = io.StringIO()
        value = None
        ok = True
        message: Optional[str] = None

        with warnings.catch_warnings(record=True) as wlist, contextlib.redirect_stdout(stdout_buf):
            warnings.simplefilter("always")
            try:
                value = self.func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                ok = False
                message = f"{type(e).__name__}: {e}"
            finally:
                warning_records = list(wlist)

        # strict policy
        if ok and self.strict >= 2 and len(warning_records) > 0:
            ok = False
            first = warning_records[0]
            message = f"Warning: {first.message}"

        if ok and self.strict >= 3:
            printed = stdout_buf.getvalue()
            if printed.strip():
                ok = False
                message = f"Message: {printed.strip()}"

        t1 = time.perf_counter()
        ended_at = _now_iso()
        elapsed = t1 - t0

        # Maybe wrap
        maybe_val = just(value) if ok else nothing()

        # Inspector g
        g_val = None
        if ok and callable(self.g):
            try:
                g_val = self.g(value)
            except Exception as e:  # noqa: BLE001
                # Don't fail the step because inspector failed; record inspector error as message
                g_val = f"<inspector error: {type(e).__name__}: {e}>"

        # Diff
        diff_obj: Union[str, List[str], None] = None
        if self.diff != "none":
            out_repr = _safe_repr(value) if ok else "<no-output>"
            if self.diff == "summary":
                diff_obj = _summarize_diff(input_repr, out_repr)
            else:
                udiff = difflib.unified_diff(
                    input_repr.splitlines(keepends=True),
                    out_repr.splitlines(keepends=True),
                    fromfile="input",
                    tofile="output",
                    n=3,
                )
                diff_obj = list(udiff)

        # Compose one-step log_df row
        row = {
            "ops_number": 1,
            "outcome": "OK! Success" if ok else "NOK! Failure",
            "function": self.fn_label if ok else self._call_signature_fallback(args, kwargs),
            "message": message,
            "start_time": started_at,
            "end_time": ended_at,
            "run_time": elapsed,
            "g": g_val,
            "diff_obj": diff_obj,
            "lag_outcome": None,
        }

        line = _format_log_line(ok, self.fn_label, started_at, elapsed)
        chron = Chronicle(value=maybe_val, log_df=[row], lines=[line])
        return chron

    def _call_signature_fallback(self, args, kwargs) -> str:
        # Useful to display a readable function call on failure
        try:
            sig = inspect.signature(self.func)
            ba = sig.bind_partial(*args, **kwargs)
            ba.apply_defaults()
            return f"{self.fn_label}{ba}"
        except Exception:  # noqa: BLE001
            return self.fn_label

def record(_func: Optional[Callable[..., Any]] = None, *, strict: int = 1, g: Optional[Callable[[Any], Any]] = None, diff: str = "none", name: Optional[str] = None):
    """
    record can be used as:
      - a function: r_sqrt = record(math.sqrt, strict=2, g=len, diff="summary")
      - a decorator: @record(strict=2, diff="full") def f(...): ...

    strict: 1 = errors only, 2 = errors + warnings, 3 = errors + warnings + printed messages
    g: an inspector function applied to the output, recorded in the log
    diff: "none" | "summary" | "full" for input/output differences
    name: optional label to display instead of __name__
    """
    def _wrap(func: Callable[..., Any]) -> RecordedFunction:
        return RecordedFunction(func, strict=strict, g=g, diff=diff, name=name)

    if _func is None:
        return _wrap
    return _wrap(_func)

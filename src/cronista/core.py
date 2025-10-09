import io
import time
import difflib
import inspect
import warnings
import contextlib
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from talvez import just, nothing

# Optional pandas support for table output
try:
    import pandas as _pd  # type: ignore
    _PANDAS_AVAILABLE = True
except Exception:
    _pd = None
    _PANDAS_AVAILABLE = False

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
        self._lines = lines or []        # per-step lines (no "Total")

    def __repr__(self) -> str:
        ok = self.is_ok()
        header = "OK! Value computed successfully:" if ok else "NOK! Value computed unsuccessfully:"
        body = f"Just({_safe_repr(self.value.value)})" if ok else "Nothing"
        return (
            f"{header}\n---------------\n{body}\n\n---------------\n"
            "This is an object of type `chronicle`.\n"
            "Retrieve the value of this object with unveil(.c, \"value\").\n"
            "To read the log of this object, call read_log(.c).\n"
        )

    def is_ok(self) -> bool:
        return hasattr(self.value, "is_just") and self.value.is_just

    def bind_record(self, rfunc: "RecordedFunction", *args, **kwargs) -> "Chronicle":
        """
        Chain another recorded function, composing logs. If current value is Nothing,
        short-circuit and append a NOK log entry for rfunc without executing it.
        """
        next_op = len(self.log_df) + 1

        if not self.is_ok():
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
            out = Chronicle(
                value=self.value,
                log_df=self.log_df + [new_row],
                lines=self._lines + [line],  # compose raw per-step lines
            )
            return out

        base_val = self.value.value
        next_ch = rfunc(base_val, *args, **kwargs)

        renumbered = []
        for i, row in enumerate(next_ch.log_df, start=1):
            nr = dict(row)
            nr["ops_number"] = next_op - 1 + i
            nr["lag_outcome"] = (
                self.log_df[-1]["outcome"] if (self.log_df and i == 1)
                else (renumbered[-1]["outcome"] if renumbered else None)
            )
            renumbered.append(nr)

        out = Chronicle(
            value=next_ch.value,
            log_df=self.log_df + renumbered,
            lines=self._lines + next_ch._lines,  # compose raw per-step lines
        )
        return out

def unveil(c: Chronicle, what: str = "value") -> Any:
    """
    unveil(chronicle, "value") -> underlying value or None
    unveil(chronicle, "log_df") -> list of dicts with detailed log rows
    unveil(chronicle, "lines") -> per-step printable log lines (no "Total")
    """
    if what == "value":
        return c.value.value if hasattr(c.value, "is_just") and c.value.is_just else None
    elif what == "log_df":
        return c.log_df
    elif what == "lines":
        return list(c._lines)
    else:
        raise ValueError('what must be one of: "value", "log_df", "lines"')

def read_log(c: Chronicle, style: str = "pretty") -> Union[List[str], Dict[str, Any], str, Any]:
    """
    Read and display the log of a chronicle in a chosen style.

    style:
      - "pretty": human-friendly lines with status, function, timestamps, runtimes, and inline messages for failures; includes a Total line
      - "table": returns a pandas.DataFrame when pandas is available (with df.attrs['total_runtime_secs']),
                 otherwise returns {'rows': [...], 'total_runtime_secs': float}
      - "errors-only": only failed steps (or a single success message if none failed)
    """
    allowed = {"pretty", "table", "errors-only"}
    if style not in allowed:
        raise ValueError(f'style must be one of {sorted(allowed)}, got {style!r}')

    rows = c.log_df or []
    total = float(sum((r.get("run_time") or 0.0) for r in rows))

    if style == "pretty":
        lines: List[str] = []
        for r in rows:
            outcome = r.get("outcome", "")
            ok = str(outcome).startswith("OK")
            fn = r.get("function", "<unknown>")
            started_at = r.get("start_time", "")
            rt = float(r.get("run_time") or 0.0)
            line = _format_log_line(ok, fn, started_at, rt)
            msg = r.get("message")
            if msg:
                line += f" — {msg}"
            lines.append(line)
        lines.append(f"Total: {total:.3f} secs")
        return lines

    if style == "table":
        table_rows: List[Dict[str, Any]] = []
        for r in rows:
            table_rows.append({
                "ops_number": r.get("ops_number"),
                "status": "OK" if str(r.get("outcome", "")).startswith("OK") else "NOK",
                "function": r.get("function"),
                "start_time": r.get("start_time"),
                "end_time": r.get("end_time"),
                "run_time_secs": float(r.get("run_time") or 0.0),
                "message": r.get("message"),
            })
        if _PANDAS_AVAILABLE and _pd is not None:
            df = _pd.DataFrame.from_records(table_rows, columns=[
                "ops_number", "status", "function", "start_time", "end_time", "run_time_secs", "message"
            ])
            # Attach total runtime as DataFrame attribute (preserves original API idea)
            try:
                df.attrs["total_runtime_secs"] = total
            except Exception:
                # attrs may fail on very old pandas; ignore silently
                pass
            return df
        else:
            return {
                "rows": table_rows,
                "total_runtime_secs": total,
            }

    # errors-only
    failed = [r for r in rows if not str(r.get("outcome", "")).startswith("OK")]
    if not failed:
        return f"All steps succeeded in {total:.3f} secs"
    out_lines: List[str] = []
    for r in failed:
        fn = r.get("function", "<unknown>")
        started_at = r.get("start_time", "")
        rt = float(r.get("run_time") or 0.0)
        line = _format_log_line(False, fn, started_at, rt)
        msg = r.get("message")
        if msg:
            line += f" — {msg}"
        out_lines.append(line)
    return out_lines

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
        started_at = _now_iso()
        t0 = time.perf_counter()
        input_repr = _safe_repr({"args": args, "kwargs": kwargs})

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

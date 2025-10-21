# cronista

A Python port of the R package [chronicler](https://github.com/b-rodrigues/chronicler): decorate functions to return an enhanced "chronicle" that contains the computed value, detailed logs, optional inspectors, and diffs. It composes across steps, so you can trace entire pipelines. Values are wrapped in `Maybe` using [talvez](https://github.com/b-rodrigues/talvez), allowing safe propagation of failures (`Nothing`) without exceptions.

## Installation

```bash
pip install -e .
```

## Quick start

```python
import math
from cronista import record, unveil, read_log

r_sqrt = record(math.sqrt)
a = r_sqrt(16)

print(unveil(a, "value"))  # 4.0

# Pretty log (default style), includes Total line and inline messages on failures
print("\n".join(read_log(a, style="pretty")))
```

## Chaining decorated functions

```python
from numpy import sqrt, exp, sum
from cronista import record, unveil

r_sqrt = record(sqrt)
r_exp = record(exp)
r_mean = record(lambda xs: sum(xs) / len(xs))

b = r_sqrt([1.0, 2.0, 3.0]).bind_record(r_exp).bind_record(r_mean)
print(unveil(b, "value"))
```

## Logging styles

- `read_log(.c, style="pretty")`: short, human-friendly lines like `OK \`sqrt\` at ... (0.000s)`, and failures include their message. Appends `Total: ... secs`.
- `read_log(.c, style="table")`: returns `{"rows": [...], "total_runtime_secs": float}` with columns `ops_number, status, function, start_time, end_time, run_time_secs, message`.
- `read_log(.c, style="errors-only")`: if all steps succeeded, returns a single string summarising success; otherwise returns only the failed steps with their messages.

```python
from cronista import record, read_log

def boom(_):
    raise RuntimeError("kapow")

r_ok = record(lambda x: x + 1)
r_boom = record(boom, strict=1)

out = r_ok(1).bind_record(r_boom)

print(read_log(out, style="pretty"))      # human lines + Total
print(read_log(out, style="table"))       # dict with rows + total
print(read_log(out, style="errors-only")) # only the failing steps
```

## Error handling


If a step fails, `Nothing` propagates and subsequent steps are logged as NOK
without being executed:

```python
r_inv = record(lambda x: 1 / x, strict=1)
bad = r_inv(0).bind_record(r_sqrt)
print(bad)           # NOK
print(read_log(bad)) # NOK lines, with short-circuit info
```

## Condition handling (strict)

- `strict=1`: only exceptions fail the step (warnings/messages are ignored).
- `strict=2`: warnings also fail the step.
- `strict=3`: warnings and printed messages (stdout) fail the step.

This mirrors chronicler’s “errors / warnings / messages” behavior using Python’s
`warnings` and captured stdout.

## Advanced logging

- Inspector `g`: record a function of the output (e.g., size/shape).

```python
from cronista import record, check_g

r_len = record(lambda s: s.strip(), g=len)
out = r_len("  hello  ")
print(check_g(out))  # [{'ops_number': 1, 'function': '<lambda>', 'g': 5}]
```

- Diffs: compare input snapshot vs output snapshot.

```python
from cronista import record, check_diff

r_upper = record(lambda s: s.upper(), diff="summary")
out = r_upper("Hello")
print(check_diff(out))  # summary of insertions/deletions/matches

r_upper_full = record(lambda s: s.upper(), diff="full")
print(check_diff(r_upper_full("Hello"))[0]["diff_obj"])  # unified diff lines
```

- Access detailed log rows:

```python
from cronista import unveil
rows = unveil(out, "log_df")
for row in rows:
    print(row["ops_number"], row["outcome"], row["function"], row["run_time"])
```

## Notes

- Values are wrapped using talvez: success → `Just(value)`, failure →
  `Nothing()`.
- `bind_record` mirrors chronicler’s `bind_record()`: composes recorded
  functions and their logs, short-circuiting on `Nothing`.
- The implementation mirrors chronicler’s vignettes and README; see the original
  docs for conceptual background on monads and the Maybe pattern.

hello class

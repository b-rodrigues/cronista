# cronista

A Python port of the R package
[chronicler](https://github.com/b-rodrigues/chronicler): decorate functions to
return an enhanced "chronicle" that contains the computed value, detailed logs,
optional inspectors, and diffs. It composes across steps, so you can trace
entire pipelines. Values are wrapped in `Maybe` using
[talvez](https://github.com/b-rodrigues/talvez), allowing safe propagation of
failures (`Nothing`) without exceptions.

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

print(a)
# OK! Value computed successfully:
# ---------------
# Just(4.0)
#
# ---------------
# This is an object of type `chronicle`.
# Retrieve the value of this object with unveil(.c, "value").
# To read the log of this object, call read_log(.c).

print(unveil(a, "value"))  # 4.0
print(read_log(a))         # ["OK `sqrt` at 12:00:00 (0.000s)"]
```

## Chaining decorated functions

`bind_record` is modeled after chronicler’s pipeline. Call it on a `Chronicle`
to pass its value to the next recorded function and compose logs.

```python
import math
from cronista import record, unveil

r_sqrt = record(math.sqrt)
r_exp = record(math.exp)
r_mean = record(lambda xs: sum(xs) / len(xs))

b = r_sqrt(1.0).bind_record(r_exp).bind_record(r_mean)  # silly chain, just for demo
print(unveil(b, "value"))
print("\n".join(read_log(b)))
```

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
  docs for conceptual background on monads and the Maybe pattern. tnn

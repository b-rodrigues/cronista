import math
from cronista import record, unveil, read_log

def test_error_propagation_short_circuit():
    # Define named functions so logs are readable
    def add1(x):
        return x + 1

    def double(x):
        return x * 2

    def will_fail(x):
        # Trigger a runtime error (division by zero)
        return 1 / 0

    executed = {"count": 0}
    def add10(x):
        # This should NOT run due to short-circuit after failure
        executed["count"] += 1
        return x + 10

    r_add1 = record(add1)
    r_double = record(double)
    r_fail = record(will_fail, strict=1)  # errors fail the step
    r_add10 = record(add10)

    # Chain: two successes -> one failure -> a step that would succeed but must be short-circuited
    out = r_add1(5).bind_record(r_double).bind_record(r_fail).bind_record(r_add10)

    # Final value is Nothing -> unveil returns None
    assert unveil(out, "value") is None

    # Verify detailed log rows: OK, OK, NOK (error), NOK (propagated short-circuit)
    rows = unveil(out, "log_df")
    assert len(rows) == 4
    assert rows[0]["outcome"] == "OK! Success"
    assert rows[1]["outcome"] == "OK! Success"
    assert rows[2]["outcome"] == "NOK! Failure"
    assert rows[3]["outcome"] == "NOK! Failure"
    assert rows[3]["message"] == "Short-circuited due to Nothing"

    # Ensure the final step was not executed
    assert executed["count"] == 0

    # Pretty log includes two NOK lines and a Total line
    lines = read_log(out, style="pretty")
    assert any(ln.startswith("NOK") for ln in lines)
    assert sum(1 for ln in lines if ln.startswith("NOK")) == 2
    assert lines[-1].startswith("Total:")

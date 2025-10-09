import math
import warnings

from cronista import record, read_log

def test_read_log_pretty_includes_messages_and_total():
    def bad(x):
        raise ValueError("boom")

    r_add = record(lambda x: x + 1)
    r_bad = record(bad, strict=1)

    out = r_add(1).bind_record(r_bad)

    lines = read_log(out, style="pretty")
    # Last line is total
    assert lines[-1].startswith("Total:")
    # The failing step line includes the message
    nok_lines = [ln for ln in lines if ln.startswith("NOK")]
    assert any("ValueError: boom" in ln for ln in nok_lines)

def test_read_log_table_has_rows_and_total(monkeypatch=None):
    def warny():
        warnings.warn("careful")
        return 10

    r_warny = record(warny, strict=2)  # warnings trigger NOK
    out = r_warny()

    try:
        import pandas as pd  # type: ignore
        have_pandas = True
    except Exception:
        have_pandas = False
        pd = None  # noqa: F841

    table = read_log(out, style="table")

    if have_pandas:
        import pandas as pd  # type: ignore
        assert isinstance(table, pd.DataFrame)
        # Columns present
        for col in ["ops_number", "status", "function", "start_time", "end_time", "run_time_secs", "message"]:
            assert col in table.columns
        # Attribute with total runtime
        assert "total_runtime_secs" in getattr(table, "attrs", {})
        assert table.shape[0] == 1
        # Message captured
        assert "careful" in (str(table.loc[0, "message"]) if not table.empty else "")
    else:
        assert isinstance(table, dict)
        assert "rows" in table and "total_runtime_secs" in table
        assert isinstance(table["rows"], list) and len(table["rows"]) == 1
        row = table["rows"][0]
        assert row["status"] == "NOK"
        assert "careful" in (row["message"] or "")

def test_read_log_errors_only_behaviour():
    # all OK -> single success message
    r_add = record(lambda x: x + 1)
    ok_out = r_add(1).bind_record(r_add)
    msg = read_log(ok_out, style="errors-only")
    assert isinstance(msg, str)
    assert msg.lower().startswith("all steps succeeded")

    # with a failure -> only failed steps listed
    def bad(_):
        print("oops")  # treated as message under strict=3
        return 42

    r_bad = record(bad, strict=3)
    fail_out = r_bad("ignored")
    errs = read_log(fail_out, style="errors-only")
    assert isinstance(errs, list) and len(errs) == 1
    assert errs[0].startswith("NOK")
    assert "Message: oops" in errs[0]
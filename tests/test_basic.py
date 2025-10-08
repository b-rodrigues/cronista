import math
from cronista import record, unveil

def test_success_and_unveil():
    r_sqrt = record(math.sqrt)
    out = r_sqrt(9.0)
    assert unveil(out, "value") == 3.0
    assert "OK" in out.read_log()[0]

def test_failure_propagation():
    r_inv = record(lambda x: 1 / x, strict=1)
    out = r_inv(0)
    assert unveil(out, "value") is None
    assert any("NOK" in line for line in out.read_log())

def test_bind_record_chain():
    r_add1 = record(lambda x: x + 1)
    r_double = record(lambda x: x * 2)
    out = r_add1(5).bind_record(r_double)
    assert unveil(out, "value") == 12

def test_inspector_and_diff():
    r_id = record(lambda x: x, g=lambda x: ("len", len(str(x))), diff="summary")
    c = r_id({"a": 1})
    rows = c.log_df
    assert rows[0]["g"][0] == "len"
    assert isinstance(rows[0]["diff_obj"], str)

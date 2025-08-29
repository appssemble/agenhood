import json

from proxy.logfmt import log_line


def test_log_line_is_valid_json_with_required_keys():
    line = log_line(level="info", msg="egress", host="example.com")
    obj = json.loads(line)
    assert obj["level"] == "info"
    assert obj["msg"] == "egress"
    assert obj["host"] == "example.com"
    # ts must be present and ISO-8601-ish (parseable suffix Z or offset)
    assert "ts" in obj and obj["ts"].endswith("Z")


def test_log_line_single_line_no_embedded_newline():
    line = log_line(level="warn", msg="egress", host="a\nb")
    assert line.count("\n") == 0           # the builder returns no trailing newline
    obj = json.loads(line)
    assert obj["host"] == "a\nb"           # newline preserved *inside* JSON string


def test_log_line_orders_ts_level_msg_first():
    line = log_line(level="info", msg="x", extra=1)
    keys = list(json.loads(line).keys())
    assert keys[0] == "ts"
    assert keys[1] == "level"
    assert keys[2] == "msg"


def test_log_line_drops_none_valued_extras():
    line = log_line(level="info", msg="x", task_id=None, host="h")
    obj = json.loads(line)
    assert "task_id" not in obj
    assert obj["host"] == "h"

from __future__ import annotations

import pytest

from agentcore.drivers.cli_stream import classify_json_line, log_payload

pytestmark = pytest.mark.unit


def test_classify_json_line_matches_driver_wrappers() -> None:
    assert classify_json_line("") == ("ignore", None)
    assert classify_json_line("   ") == ("ignore", None)
    assert classify_json_line('{"type":"result"}') == ("event", {"type": "result"})
    assert classify_json_line("not json") == ("stdout", "not json")
    assert classify_json_line("{bad") == ("stdout", "{bad")


def test_log_payload_keeps_op_and_adds_normalized_shape() -> None:
    payload = log_payload("skills_materialized", data={"count": 2})
    assert payload == {
        "op": "skills_materialized",
        "level": "info",
        "message": "skills_materialized",
        "data": {"count": 2},
        "count": 2,
    }

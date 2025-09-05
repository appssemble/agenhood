import json

import pytest

from control_plane.sse import format_sse, parse_event_line, should_forward

pytestmark = pytest.mark.unit


def test_format_sse_wraps_payload_with_double_newline():
    out = format_sse('{"seq": 3}')
    assert out == 'data: {"seq": 3}\n\n'


def test_parse_event_line_extracts_seq():
    line = 'data: ' + json.dumps({"seq": 7, "type": "log", "ts": "t", "payload": {}})
    ev = parse_event_line(line)
    assert ev is not None
    assert ev["seq"] == 7
    assert ev["type"] == "log"


def test_parse_event_line_ignores_non_data_lines():
    assert parse_event_line("") is None
    assert parse_event_line(": keep-alive") is None
    assert parse_event_line("event: ping") is None


def test_should_forward_respects_after_seq():
    # after_seq=5 → forward strictly seq>5
    assert should_forward(seq=6, after_seq=5) is True
    assert should_forward(seq=5, after_seq=5) is False
    assert should_forward(seq=1, after_seq=5) is False
    # after_seq=None → forward everything
    assert should_forward(seq=1, after_seq=None) is True

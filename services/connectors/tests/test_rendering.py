import pytest

from connectors.rendering import TranscriptRenderer

pytestmark = pytest.mark.unit


def test_assistant_messages_accumulate():
    r = TranscriptRenderer(surface=["reasoning", "result"])
    r.ingest({"type": "assistant_message",
              "payload": {"content": [{"type": "text", "text": "step one"}]}})
    r.ingest({"type": "assistant_message",
              "payload": {"content": [{"type": "text", "text": "step two"}]}})
    body = r.render()
    assert "step one" in body and "step two" in body
    assert body.startswith("🤖")  # working header while not final


def test_tool_lines_only_when_surfaced():
    r = TranscriptRenderer(surface=["reasoning"])  # no "tools"
    r.ingest({"type": "tool_call", "payload": {"name": "bash", "input": {"command": "ls"}}})
    assert "bash" not in r.render()
    r2 = TranscriptRenderer(surface=["reasoning", "tools"])
    r2.ingest({"type": "tool_call", "payload": {"name": "bash", "input": {"command": "ls"}}})
    assert "bash" in r2.render()


def test_terminal_status_finalizes():
    r = TranscriptRenderer(surface=["reasoning", "result"])
    r.ingest({"type": "assistant_message",
              "payload": {"content": [{"type": "text", "text": "working"}]}})
    done = r.ingest({"type": "status_change",
                     "payload": {"to": "succeeded", "result": {"output": "ALL DONE"},
                                 "error": None}})
    assert done is True
    body = r.render()
    assert r.is_final
    assert "ALL DONE" in body
    assert "✅" in body


def test_truncation_caps_length():
    r = TranscriptRenderer(surface=["reasoning"], max_chars=50)
    r.ingest({"type": "assistant_message",
              "payload": {"content": [{"type": "text", "text": "x" * 200}]}})
    body = r.render()
    assert len(body) <= 50 + 20  # cap + marker slack
    assert "…(continued)" in body

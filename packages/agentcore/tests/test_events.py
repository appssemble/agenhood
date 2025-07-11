import typing

from agentcore import events
from agentcore.models import EventType


def test_event_types_match_the_model_literal():
    assert events.EVENT_TYPES == frozenset(typing.get_args(EventType))


def test_task_started_payload():
    assert events.task_started("vanilla", "claude-opus-4-7") == {
        "driver": "vanilla",
        "model": "claude-opus-4-7",
    }


def test_tool_result_payload_shape():
    payload = events.tool_result("tu_1", ok=True, content="done", duration_ms=42)
    assert payload == {
        "tool_use_id": "tu_1",
        "ok": True,
        "content": "done",
        "duration_ms": 42,
    }


def test_token_update_is_cumulative_counts():
    assert events.token_update(tokens_in=100, tokens_out=20) == {
        "tokens_in": 100,
        "tokens_out": 20,
    }


def test_status_change_carries_result_and_error_slots():
    payload = events.status_change(
        from_status="running", to_status="completed", result={"ok": True}, error=None
    )
    assert payload == {
        "from": "running",
        "to": "completed",
        "result": {"ok": True},
        "error": None,
    }


def test_log_payload_levels_and_data():
    assert events.log("warn", "iteration limit", data={"limit": 30}) == {
        "level": "warn",
        "message": "iteration limit",
        "data": {"limit": 30},
    }

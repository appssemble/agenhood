import pytest

pytestmark = pytest.mark.unit


def test_build_command_without_resume_session_id_unchanged():
    from agentcore.drivers.opencode import build_command

    cmd = build_command(workspace="/ws", model_ref="anthropic/claude-opus-4-8", prompt="hi")
    assert cmd == [
        "opencode", "run", "--dir", "/ws", "--format", "json",
        "-m", "anthropic/claude-opus-4-8", "--dangerously-skip-permissions", "--", "hi",
    ]


def test_build_command_with_resume_session_id():
    from agentcore.drivers.opencode import build_command

    cmd = build_command(
        workspace="/ws", model_ref="anthropic/claude-opus-4-8", prompt="continue",
        resume_session_id="ses_abc123",
    )
    assert cmd == [
        "opencode", "run", "--dir", "/ws", "--format", "json",
        "-m", "anthropic/claude-opus-4-8", "--dangerously-skip-permissions",
        "-s", "ses_abc123", "--", "continue",
    ]


def test_event_session_id_extracts_top_level_field():
    from agentcore.drivers.opencode import event_session_id

    assert event_session_id({"type": "text", "sessionID": "ses_x", "part": {}}) == "ses_x"
    assert event_session_id({"type": "step_finish", "sessionID": "ses_x"}) == "ses_x"


def test_event_session_id_missing_returns_none():
    from agentcore.drivers.opencode import event_session_id

    assert event_session_id({"type": "text"}) is None
    assert event_session_id({"sessionID": ""}) is None
    assert event_session_id({"sessionID": 5}) is None

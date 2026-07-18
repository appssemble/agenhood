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


def test_build_command_appends_variant_before_prompt_separator():
    from agentcore.drivers.opencode import build_command

    cmd = build_command(
        workspace="/ws", model_ref="openai/gpt-5.6", prompt="hi", effort="medium"
    )
    assert cmd.index("--variant") < cmd.index("--")
    assert cmd[cmd.index("--variant") + 1] == "medium"


def test_build_command_no_variant_when_unset():
    from agentcore.drivers.opencode import build_command

    cmd = build_command(workspace="/ws", model_ref="openai/gpt-5.6", prompt="hi")
    assert "--variant" not in cmd


def test_write_system_prompt_instructions_wires_config(tmp_path):
    import json
    import pathlib

    from agentcore.drivers.opencode import (
        opencode_config_path,
        write_system_prompt_instructions,
    )

    ws = str(tmp_path)
    path = write_system_prompt_instructions(ws, "Answer in French.")
    assert path is not None
    assert pathlib.Path(path).read_text() == "Answer in French."
    cfg = json.loads(pathlib.Path(opencode_config_path(ws)).read_text())
    assert cfg["instructions"] == [path]


def test_write_system_prompt_instructions_clears_when_empty(tmp_path):
    import json
    import pathlib

    from agentcore.drivers.opencode import (
        opencode_config_path,
        write_system_prompt_instructions,
    )

    ws = str(tmp_path)
    first = write_system_prompt_instructions(ws, "old")
    assert first is not None
    assert write_system_prompt_instructions(ws, "") is None
    assert not pathlib.Path(first).exists()
    cfg = json.loads(pathlib.Path(opencode_config_path(ws)).read_text())
    assert "instructions" not in cfg or cfg["instructions"] == []

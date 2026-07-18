import pytest

pytestmark = pytest.mark.unit


def test_claude_event_types_registered():
    from agentcore.events import EVENT_TYPES

    assert "claude_event" in EVENT_TYPES
    assert "claude_stdout" in EVENT_TYPES


def test_claude_event_builders():
    from agentcore import events

    assert events.claude_stdout("hi") == {"line": "hi"}
    assert events.claude_event({"type": "result"}) == {"raw": {"type": "result"}}


def test_model_arg_strips_anthropic_prefix():
    from agentcore.drivers.claude_code import model_arg

    assert model_arg("anthropic/claude-opus-4-8") == "claude-opus-4-8"
    assert model_arg("claude-opus-4-8") == "claude-opus-4-8"


def test_claude_home_and_dirs_under_workspace():
    from agentcore.drivers.claude_code import claude_home, mcp_config_path, skills_dir

    assert claude_home("/workspace") == "/workspace/.agent-state/claude-code"
    assert skills_dir("/workspace") == "/workspace/.agent-state/claude-code/.claude/skills"
    assert mcp_config_path("/workspace") == "/workspace/.agent-state/claude-code/.claude/mcp.json"


def test_build_command_without_mcp():
    from agentcore.drivers.claude_code import build_command

    assert build_command(workspace="/ws", model="claude-opus-4-8") == [
        "claude", "-p", "--output-format", "stream-json", "--verbose",
        "--model", "claude-opus-4-8", "--dangerously-skip-permissions",
    ]


def test_build_command_with_mcp_adds_strict_flags():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="claude-opus-4-8", mcp_config="/ws/mcp.json")
    assert cmd[-3:] == ["--strict-mcp-config", "--mcp-config", "/ws/mcp.json"]


def test_build_env_api_key_sets_anthropic_key():
    from agentcore.drivers.claude_code import build_env

    env = build_env({}, credential="sk-ant-1", credential_kind="api_key",
                    home="/ws/.agent-state/claude-code")
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-1"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["HOME"] == "/ws/.agent-state/claude-code"


def test_build_env_oauth_sets_oauth_token():
    from agentcore.drivers.claude_code import build_env

    env = build_env({}, credential="sk-ant-oat01-x", credential_kind="oauth_subscription",
                    home="/ws/.agent-state/claude-code")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-x"
    assert "ANTHROPIC_API_KEY" not in env


def test_build_env_unknown_kind_raises():
    import pytest as _pytest

    from agentcore.drivers.claude_code import build_env
    with _pytest.raises(ValueError):
        build_env({}, credential="x", credential_kind="oauth", home="/h")


def test_build_env_starts_from_allowlist(monkeypatch):
    monkeypatch.setenv("SHIM_TOKEN", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    from agentcore import sandbox
    from agentcore.drivers import claude_code

    env = claude_code.build_env(sandbox.build_child_env(), credential="k",
                                credential_kind="api_key",
                                home="/workspace/.agent-state/claude-code")
    assert "SHIM_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == "k"


def test_parse_claude_line_classifies():
    from agentcore.drivers.claude_code import parse_claude_line

    assert parse_claude_line("") == ("ignore", None)
    assert parse_claude_line("   ") == ("ignore", None)
    assert parse_claude_line('{"type":"result"}') == ("event", {"type": "result"})
    assert parse_claude_line("not json") == ("stdout", "not json")
    assert parse_claude_line("{bad") == ("stdout", "{bad")


def test_result_text_only_on_success():
    from agentcore.drivers.claude_code import result_text

    assert result_text({"type": "result", "subtype": "success", "result": "done"}) == "done"
    assert result_text({"type": "result", "subtype": "error_max_turns", "result": "x"}) is None
    assert result_text({"type": "assistant"}) is None


def test_result_usage_maps_tokens():
    from agentcore.drivers.claude_code import result_usage

    ev = {"type": "result", "usage": {"input_tokens": 100, "output_tokens": 20,
                                      "cache_read_input_tokens": 90}}
    assert result_usage(ev) == (100, 20)
    bad = {"type": "result", "usage": {"input_tokens": True, "output_tokens": 1}}
    assert result_usage(bad) is None
    assert result_usage({"type": "assistant"}) is None


def test_result_error_message():
    from agentcore.drivers.claude_code import result_error

    assert result_error({"type": "result", "is_error": True, "result": "boom"}) == "boom"
    assert result_error({"type": "result", "subtype": "success", "is_error": False}) is None
    assert result_error({"type": "assistant"}) is None


def test_build_command_with_resume_session_id():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="claude-opus-4-8", resume_session_id="sess-abc")
    assert cmd == [
        "claude", "-p", "--output-format", "stream-json", "--verbose",
        "--model", "claude-opus-4-8", "--dangerously-skip-permissions",
        "-r", "sess-abc",
    ]


def test_build_command_without_resume_session_id_unchanged():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="claude-opus-4-8")
    assert "-r" not in cmd


def test_event_session_id_extracts_field():
    from agentcore.drivers.claude_code import event_session_id

    assert event_session_id({"type": "system", "subtype": "init", "session_id": "abc-123"}) == "abc-123"
    assert event_session_id({"type": "assistant", "session_id": "abc-123"}) == "abc-123"


def test_event_session_id_missing_returns_none():
    from agentcore.drivers.claude_code import event_session_id

    assert event_session_id({"type": "assistant"}) is None
    assert event_session_id({"session_id": ""}) is None
    assert event_session_id({"session_id": 123}) is None


def test_build_command_appends_effort_flag():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="opus", effort="low")
    i = cmd.index("--effort")
    assert cmd[i + 1] == "low"


def test_build_command_no_effort_flag_when_unset():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="opus")
    assert "--effort" not in cmd


def test_build_command_appends_configured_system_prompt():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(
        workspace="/ws", model="opus",
        system_prompt="You are a security auditor.", system_prompt_mode="augment",
    )
    i = cmd.index("--append-system-prompt")
    assert cmd[i + 1] == "You are a security auditor."
    assert "--system-prompt" not in cmd


def test_build_command_replace_mode_uses_system_prompt_flag():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(
        workspace="/ws", model="opus",
        system_prompt="Only this.", system_prompt_mode="replace",
    )
    i = cmd.index("--system-prompt")
    assert cmd[i + 1] == "Only this."
    assert "--append-system-prompt" not in cmd


def test_build_command_no_prompt_flags_when_unset():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="opus")
    assert "--append-system-prompt" not in cmd
    assert "--system-prompt" not in cmd


def test_build_command_includes_json_schema():
    from agentcore.drivers.claude_code import build_command

    cmd = build_command(workspace="/ws", model="m", json_schema='{"type":"object"}')
    i = cmd.index("--json-schema")
    assert cmd[i + 1] == '{"type":"object"}'


def test_build_command_omits_json_schema_by_default():
    from agentcore.drivers.claude_code import build_command

    assert "--json-schema" not in build_command(workspace="/ws", model="m")


def test_result_structured_output():
    from agentcore.drivers.claude_code import result_structured_output

    ev = {"type": "result", "subtype": "success", "structured_output": {"a": 1}}
    assert result_structured_output(ev) == {"a": 1}
    assert result_structured_output({"type": "result", "is_error": True,
                                     "structured_output": {"a": 1}}) is None
    assert result_structured_output({"type": "assistant"}) is None

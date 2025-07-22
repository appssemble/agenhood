import asyncio
import json

import agentcore.drivers.opencode as oc  # noqa: F401  (self-registers on import)
from agentcore.drivers.base import DRIVERS
from agentcore.drivers.opencode import (
    build_command,
    build_env,
    event_error,
    event_text,
    model_ref,
    parse_opencode_line,
    provider_for_model,
    workspace_xdg,
)
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody


def test_registers_under_name_opencode():
    assert "opencode" in DRIVERS
    assert DRIVERS["opencode"].name == "opencode"


def test_capabilities():
    d = DRIVERS["opencode"]
    assert d.capabilities.supports_tools is False
    assert d.capabilities.supports_structured_output is False
    assert d.capabilities.supports_cancel is True
    assert d.capabilities.requires_image_feature is None


def test_default_template_owns_its_tools():
    tpl = DRIVERS["opencode"].default_template
    assert tpl.driver == "opencode"
    assert tpl.available_tools == []
    assert tpl.tools_user_editable is False


def test_parse_structured_event_line():
    kind, value = parse_opencode_line('{"type":"text","part":{"text":"hello"}}')
    assert kind == "event"
    assert value == {"type": "text", "part": {"text": "hello"}}


def test_parse_plain_stdout_line():
    kind, value = parse_opencode_line("just some log output")
    assert kind == "stdout"
    assert value == "just some log output"


def test_parse_blank_line_ignored():
    kind, value = parse_opencode_line("   ")
    assert kind == "ignore"
    assert value is None


def test_provider_for_model():
    assert provider_for_model("claude-sonnet-4-6") == "anthropic"
    assert provider_for_model("claude-opus-4-7") == "anthropic"
    assert provider_for_model("gpt-5.1-codex") == "openai"
    assert provider_for_model("o3-mini") == "openai"
    assert provider_for_model("o4") == "openai"
    # Unknown prefixes default to anthropic (the historical default).
    assert provider_for_model("mistral-large") == "anthropic"
    # Fully-qualified ids take the provider from the prefix.
    assert provider_for_model("opencode/deepseek-v4-flash-free") == "opencode"
    assert provider_for_model("anthropic/claude-sonnet-4-6") == "anthropic"


def test_model_ref_passthrough_and_prefix():
    # Already-qualified ids pass through unchanged (no double-prefix).
    assert model_ref("opencode/deepseek-v4-flash-free") == "opencode/deepseek-v4-flash-free"
    # Bare ids are prefixed with the resolved provider.
    assert model_ref("claude-sonnet-4-6") == "anthropic/claude-sonnet-4-6"
    assert model_ref("gpt-4o") == "openai/gpt-4o"


def test_workspace_xdg_points_into_workspace():
    xdg = workspace_xdg("/workspace")
    base = "/workspace/.agent-state/opencode"
    assert xdg["XDG_DATA_HOME"] == f"{base}/data"
    assert xdg["XDG_CONFIG_HOME"] == f"{base}/config"
    assert xdg["XDG_CACHE_HOME"] == f"{base}/cache"
    assert xdg["HOME"] == base
    assert all(v.startswith(base) for v in xdg.values())


def test_opencode_xdg_is_under_agent_state():
    from agentcore.drivers import opencode
    xdg = opencode.workspace_xdg("/workspace")
    assert xdg["XDG_DATA_HOME"].startswith("/workspace/.agent-state/opencode/")
    assert xdg["HOME"].startswith("/workspace/.agent-state/opencode")


def test_opencode_skills_dir_under_agent_state():
    from agentcore.drivers import opencode
    assert "/.agent-state/opencode/" in opencode.skills_dir("/workspace")


def test_build_env_keyless_sets_no_key():
    # opencode free models run keyless: empty credential -> no key env var.
    env = build_env({"PATH": "/usr/bin"}, provider="opencode", credential="")
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_event_text_extracts_assistant_text():
    ev = {"type": "text", "part": {"type": "text", "text": "HELLO_FROM_OPENCODE"}}
    assert event_text(ev) == "HELLO_FROM_OPENCODE"
    # Non-text events / malformed parts → None.
    assert event_text({"type": "step_start", "part": {"type": "step-start"}}) is None
    assert event_text({"type": "text", "part": {}}) is None


def test_event_error_extracts_message():
    ev = {
        "type": "error",
        "error": {"name": "UnknownError", "data": {"message": "Model not found: x"}},
    }
    assert event_error(ev) == "Model not found: x"
    # Falls back to the error name when there's no data.message.
    assert event_error({"type": "error", "error": {"name": "Boom"}}) == "Boom"
    # Non-error events → None.
    assert event_error({"type": "text", "part": {"text": "hi"}}) is None


def test_build_command_uses_opencode_1x_flags():
    cmd = build_command(
        workspace="/workspace", model_ref="anthropic/claude-sonnet-4-6", prompt="do it"
    )
    assert cmd[:2] == ["opencode", "run"]
    assert "--dir" in cmd and cmd[cmd.index("--dir") + 1] == "/workspace"
    assert "--format" in cmd and cmd[cmd.index("--format") + 1] == "json"
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "anthropic/claude-sonnet-4-6"
    assert "--dangerously-skip-permissions" in cmd
    # The prompt is the final positional, guarded by ``--``.
    assert cmd[-2] == "--"
    assert cmd[-1] == "do it"
    # The removed 0.x flags must be gone.
    assert "--workspace" not in cmd
    assert "--prompt-file" not in cmd
    assert "--json-events" not in cmd


def test_build_env_sets_provider_key_and_preserves_path():
    env = build_env({"PATH": "/usr/bin"}, provider="anthropic", credential="sk-ant-xyz")
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xyz"
    assert env["PATH"] == "/usr/bin"

    oai = build_env({"PATH": "/usr/bin"}, provider="openai", credential="sk-oai-xyz")
    assert oai["OPENAI_API_KEY"] == "sk-oai-xyz"
    assert "ANTHROPIC_API_KEY" not in oai


# ---------------------------------------------------------------------------
# Token usage — opencode emits per-step usage in --format json; the driver must
# surface it as cumulative token_update events (parity with the vanilla driver).
#
# Real opencode-ai@1.15.13 shape (the version pinned in images/agent/Dockerfile).
# In --format json the `run` command prints, per completed model step:
#   {"type":"step_finish","timestamp":..,"sessionID":"..",
#    "part":{"type":"step-finish","cost":..,
#            "tokens":{"total":..,"input":..,"output":..,"reasoning":..,
#                      "cache":{"read":..,"write":..}}}}
# `part.tokens` is the usage for THAT step (AI-SDK finish-step semantics); the
# cumulative total is NOT re-emitted in json mode, so the driver accumulates.
# ---------------------------------------------------------------------------

_STEP_FINISH = {
    "type": "step_finish",
    "timestamp": 1730000000000,
    "sessionID": "ses_abc",
    "part": {
        "id": "prt_x",
        "sessionID": "ses_abc",
        "messageID": "msg_y",
        "type": "step-finish",
        "reason": "stop",
        "cost": 0.0012,
        "tokens": {
            "total": 150,
            "input": 100,
            "output": 50,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
    },
}


def test_event_tokens_extracts_step_finish_input_output():
    # input -> tokens_in, output -> tokens_out (mirrors the vanilla/Anthropic map).
    assert oc.event_tokens(_STEP_FINISH) == (100, 50)


def test_event_tokens_returns_none_for_non_step_finish_events():
    assert oc.event_tokens({"type": "text", "part": {"text": "hi"}}) is None
    assert oc.event_tokens({"type": "step_start", "part": {"type": "step-start"}}) is None
    assert oc.event_tokens(
        {"type": "error", "error": {"name": "Boom"}}
    ) is None


def test_event_tokens_returns_none_when_usage_absent_or_malformed():
    # step_finish with no part / no tokens / non-numeric values → None (defensive).
    assert oc.event_tokens({"type": "step_finish"}) is None
    assert oc.event_tokens({"type": "step_finish", "part": {}}) is None
    assert oc.event_tokens(
        {"type": "step_finish", "part": {"tokens": {"output": 5}}}
    ) is None
    assert oc.event_tokens(
        {"type": "step_finish", "part": {"tokens": {"input": "x", "output": 5}}}
    ) is None


class _FakeStdout:
    """Yields scripted byte lines, then b'' (EOF), like StreamReader.readline."""

    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class _FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = _FakeStdout(lines)
        self.returncode = returncode
        self.terminated = False

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


async def test_run_emits_cumulative_token_update(tmp_path, monkeypatch):
    """Two step_finish events with per-step usage must surface as CUMULATIVE
    token_update events, so the last value the shim/control-plane persists is the
    task total — matching the vanilla driver's contract.

    Per-step: (100,50) then (200,30) → cumulative (100,50) then (300,80).
    """
    lines = [
        (json.dumps(_STEP_FINISH) + "\n").encode(),
        (
            json.dumps(
                {
                    "type": "step_finish",
                    "timestamp": 1730000000001,
                    "sessionID": "ses_abc",
                    "part": {
                        "type": "step-finish",
                        "cost": 0.002,
                        "tokens": {
                            "total": 230,
                            "input": 200,
                            "output": 30,
                            "reasoning": 0,
                            "cache": {"read": 0, "write": 0},
                        },
                    },
                }
            )
            + "\n"
        ).encode(),
        (
            json.dumps(
                {"type": "text", "part": {"type": "text", "text": "done"}}
            )
            + "\n"
        ).encode(),
    ]

    async def fake_create(*args, **kwargs):
        return _FakeProc(lines, returncode=0)

    monkeypatch.setattr(oc.asyncio, "create_subprocess_exec", fake_create)

    events: list[tuple[str, dict]] = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    await oc.OpencodeDriver().run(
        task=TaskBody(prompt="do it"),
        config=AgentConfig(driver="opencode", model="opencode/zen-free"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=30),
        credential="",
        emit=emit,
        cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    token_updates = [p for (t, p) in events if t == "token_update"]
    assert [(p["tokens_in"], p["tokens_out"]) for p in token_updates] == [
        (100, 50),
        (300, 80),
    ]
    # The final (cumulative) value is what downstream overwrites with → the total.
    assert (token_updates[-1]["tokens_in"], token_updates[-1]["tokens_out"]) == (300, 80)
    # And the run still reaches a terminal completed status.
    statuses = [p["to"] for (t, p) in events if t == "status_change"]
    assert statuses[-1] == "completed"

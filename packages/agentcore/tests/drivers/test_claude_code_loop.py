import asyncio

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody

pytestmark = pytest.mark.unit

LIMITS = ResolvedLimits(max_iterations=1, max_tokens=1000, timeout_seconds=30)


def cfg(model="claude-opus-4-8"):
    return AgentConfig(driver="claude-code", model=model)


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


class FakeStdin:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b

    async def drain(self):
        pass

    def close(self):
        pass


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout([ln.encode() if isinstance(ln, str) else ln for ln in lines])
        self.returncode = None
        self._final_rc = returncode

    def terminate(self):
        self.returncode = -15

    async def wait(self):
        self.returncode = self._final_rc
        return self._final_rc


def patch_proc(monkeypatch, proc):
    async def fake_spawn(argv, *, cwd, env, **kwargs):
        proc.returncode = None
        return proc

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    # ensure_agent_dir is left real (not stubbed): it's a plain os.makedirs in
    # non-root test environments, and session_state.write_session_state relies
    # on it to actually create the on-disk sessions/ dir on a session's first turn.


@pytest.mark.asyncio
async def test_run_success_returns_result_text(monkeypatch, tmp_path):
    lines = [
        '{"type":"system","subtype":"init"}\n',
        '{"type":"result","subtype":"success","result":"all done",'
        '"is_error":false,"usage":{"input_tokens":10,"output_tokens":3}}\n',
    ]
    proc = FakeProc(lines, returncode=0)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="sk-ant-1", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is True
    assert result.output == "all done"
    assert any(t == "token_update" and p["tokens_out"] == 3 for t, p in events)
    assert any(t == "status_change" and p["to"] == "completed" for t, p in events)


@pytest.mark.asyncio
async def test_run_error_result_fails(monkeypatch, tmp_path):
    lines = [
        '{"type":"result","subtype":"error_during_execution","is_error":true,'
        '"result":"kaboom"}\n',
    ]
    proc = FakeProc(lines, returncode=1)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="sk-ant-1", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert "kaboom" in (result.reason or "")


@pytest.mark.asyncio
async def test_run_cancellation(monkeypatch, tmp_path):
    proc = FakeProc(['{"type":"system"}\n'], returncode=0)
    patch_proc(monkeypatch, proc)
    cancel = asyncio.Event()
    cancel.set()
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="k", emit=emit, cancel=cancel,
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert result.reason == "cancelled"
    assert any(t == "status_change" and p["to"] == "cancelled" for t, p in events)


@pytest.mark.asyncio
async def test_run_timeout(monkeypatch, tmp_path):
    # stdout never EOFs (lines keep returning); timeout_seconds=0 makes the
    # wall-clock check fire on the first loop iteration.
    proc = FakeProc(['{"type":"system"}\n'] * 100, returncode=0)
    patch_proc(monkeypatch, proc)
    limits = ResolvedLimits(max_iterations=1, max_tokens=1000, timeout_seconds=0)
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=limits,
        credential="k", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert result.reason == "timeout"
    assert any(t == "status_change" and p["to"] == "timed_out" for t, p in events)


@pytest.mark.asyncio
async def test_run_rc0_error_result_fails(monkeypatch, tmp_path):
    # rc=0 but the result event reports is_error=True — isolates the
    # `error_msg is None` success guard (rc alone would say success).
    lines = [
        '{"type":"result","subtype":"error_during_execution","is_error":true,'
        '"result":"kaboom"}\n',
    ]
    proc = FakeProc(lines, returncode=0)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="k", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert "kaboom" in (result.reason or "")


@pytest.mark.asyncio
async def test_run_missing_binary(monkeypatch, tmp_path):
    async def fake_spawn(argv, *, cwd, env, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)
    events, emit = collector()

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    result = await ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="k", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert result.reason == "claude_code_unavailable"
    assert any(t == "status_change" and p["to"] == "failed" for t, p in events)


def test_driver_registered():
    import agentcore.drivers  # noqa: F401
    from agentcore.drivers.base import DRIVERS

    assert "claude-code" in DRIVERS
    assert DRIVERS["claude-code"].capabilities.supports_mcp is True


def _cfg():
    return AgentConfig(driver="claude-code", model="claude-opus-4-8")


def _limits():
    return ResolvedLimits(max_iterations=1, max_tokens=1000, timeout_seconds=30)


@pytest.mark.asyncio
async def test_run_materializes_skills_and_mcp(monkeypatch, tmp_path):
    from agentcore.drivers import claude_code
    from agentcore.models import ShimMcpServer, ShimSkill

    captured: dict = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured["argv"] = argv
        return FakeProc([
            b'{"type":"result","subtype":"success","result":"ok","is_error":false,'
            b'"usage":{"input_tokens":1,"output_tokens":1}}\n',
        ])

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)
    monkeypatch.setattr("agentcore.sandbox.chown_to_agent", lambda *a, **k: None)

    ws = str(tmp_path / "ws")

    async def _emit(t, p):
        pass

    result = await claude_code.ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=_cfg(), limits=_limits(),
        credential="k", emit=_emit, cancel=asyncio.Event(), workspace=ws,
        skills=[ShimSkill(name="demo", description="d", body="hello")],
        mcp_servers=[ShimMcpServer(name="gh", url="https://x", auth_type="none")],
    )
    assert result.success is True
    # skill written under the discovery dir
    skill_md = (
        tmp_path / "ws" / ".agent-state" / "claude-code" / ".claude"
        / "skills" / "demo" / "SKILL.md"
    )
    assert skill_md.exists()
    # mcp config written and passed to claude
    assert (tmp_path / "ws" / ".agent-state" / "claude-code" / ".claude" / "mcp.json").exists()
    assert "--mcp-config" in captured["argv"]


@pytest.mark.asyncio
async def test_run_uses_makedirs_agent_for_skills_dir(monkeypatch, tmp_path):
    """Regression (found via live E2E verification against a real hardened
    container): claude's own resumable transcript lives under
    `.claude/projects/`, a sibling of `.claude/skills/`. ensure_agent_dir only
    chowns the leaf it's given, so it left `.claude` itself root-owned the
    first time it was created as a side effect of making `.claude/skills` —
    silently blocking claude's transcript writes and breaking session resume.
    makedirs_agent chowns every newly-created directory in the path, not just
    the leaf, so `.claude` ends up agent-owned too.
    """
    from agentcore.drivers import claude_code

    calls: list[str] = []
    monkeypatch.setattr(
        "agentcore.sandbox.makedirs_agent", lambda p, *a, **k: calls.append(p)
    )
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)
    monkeypatch.setattr("agentcore.sandbox.chown_to_agent", lambda *a, **k: None)

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        return FakeProc([
            b'{"type":"result","subtype":"success","result":"ok","is_error":false,'
            b'"usage":{"input_tokens":1,"output_tokens":1}}\n',
        ])

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)

    async def _emit(t, p):
        pass

    ws = str(tmp_path / "ws")
    await claude_code.ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=_cfg(), limits=_limits(),
        credential="k", emit=_emit, cancel=asyncio.Event(), workspace=ws,
    )

    assert calls == [claude_code.skills_dir(ws)]


@pytest.mark.asyncio
async def test_run_no_mcp_flag_when_no_servers(monkeypatch, tmp_path):
    from agentcore.drivers import claude_code

    captured: dict = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured["argv"] = argv
        return FakeProc([
            b'{"type":"result","subtype":"success","result":"ok","is_error":false,'
            b'"usage":{"input_tokens":1,"output_tokens":1}}\n',
        ])

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)
    monkeypatch.setattr("agentcore.sandbox.chown_to_agent", lambda *a, **k: None)

    async def _emit(t, p):
        pass

    await claude_code.ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=_cfg(), limits=_limits(),
        credential="k", emit=_emit, cancel=asyncio.Event(),
        workspace=str(tmp_path / "ws2"),
    )
    assert "--mcp-config" not in captured["argv"]


@pytest.mark.asyncio
async def test_run_skills_error_is_best_effort(monkeypatch, tmp_path):
    """A write_skills failure must not change the task outcome."""
    from agentcore.drivers import claude_code
    from agentcore.models import ShimSkill

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        return FakeProc([
            b'{"type":"result","subtype":"success","result":"ok","is_error":false,'
            b'"usage":{"input_tokens":1,"output_tokens":1}}\n',
        ])
    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)
    monkeypatch.setattr("agentcore.sandbox.chown_to_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        "agentcore.drivers.claude_code.write_skills",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    events = []
    async def _emit(t, p): events.append((t, p))

    result = await claude_code.ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=_cfg(), limits=_limits(),
        credential="k", emit=_emit, cancel=asyncio.Event(),
        workspace=str(tmp_path / "ws3"),
        skills=[ShimSkill(name="demo", description="d", body="hello")],
    )
    assert result.success is True
    assert any(p.get("message") == "skills_error" for _, p in events)


@pytest.mark.asyncio
async def test_run_mcp_error_is_best_effort(monkeypatch, tmp_path):
    """An MCP write failure must not change the task outcome."""
    from agentcore.drivers import claude_code
    from agentcore.models import ShimMcpServer

    captured: dict = {}
    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured["argv"] = argv
        return FakeProc([
            b'{"type":"result","subtype":"success","result":"ok","is_error":false,'
            b'"usage":{"input_tokens":1,"output_tokens":1}}\n',
        ])
    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **k: None)
    monkeypatch.setattr("agentcore.sandbox.chown_to_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        "agentcore.drivers.claude_code.render_claude_mcp_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("render failed")),
    )
    events = []
    async def _emit(t, p): events.append((t, p))

    result = await claude_code.ClaudeCodeDriver().run(
        task=TaskBody(prompt="hi"), config=_cfg(), limits=_limits(),
        credential="k", emit=_emit, cancel=asyncio.Event(),
        workspace=str(tmp_path / "ws4"),
        mcp_servers=[ShimMcpServer(name="gh", url="https://x", auth_type="none")],
    )
    assert result.success is True
    assert "--mcp-config" not in captured["argv"]
    assert any(p.get("message") == "mcp_error" for _, p in events)


@pytest.mark.asyncio
async def test_claude_session_first_turn_writes_state_file(monkeypatch, tmp_path):
    from agentcore.drivers.claude_code import ClaudeCodeDriver

    lines = [
        '{"type":"system","subtype":"init","session_id":"claude-sess-1"}',
        '{"type":"result","subtype":"success","result":"hi","usage":{"input_tokens":5,"output_tokens":2}}',
    ]
    proc = FakeProc(lines, returncode=0)
    patch_proc(monkeypatch, proc)

    driver = ClaudeCodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hello"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-1", session_is_continuation=False,
    )

    assert result.success is True
    from agentcore.drivers.session_state import read_session_state
    assert read_session_state(str(tmp_path), "claude-code", "sess-1") == {
        "claude_session_id": "claude-sess-1"
    }


@pytest.mark.asyncio
async def test_claude_session_continuation_passes_resume_flag(monkeypatch, tmp_path):
    from agentcore.drivers.claude_code import ClaudeCodeDriver
    from agentcore.drivers.session_state import write_session_state

    write_session_state(str(tmp_path), "claude-code", "sess-2", {"claude_session_id": "claude-sess-1"})

    captured_cmd = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured_cmd["argv"] = argv
        proc = FakeProc(
            ['{"type":"result","subtype":"success","result":"ok","session_id":"claude-sess-1",'
             '"usage":{"input_tokens":1,"output_tokens":1}}'],
            returncode=0,
        )
        return proc

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)

    driver = ClaudeCodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="continue"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-2", session_is_continuation=True,
    )

    assert result.success is True
    assert "-r" in captured_cmd["argv"]
    assert captured_cmd["argv"][captured_cmd["argv"].index("-r") + 1] == "claude-sess-1"


@pytest.mark.asyncio
async def test_claude_session_missing_state_fails_fast(tmp_path):
    from agentcore.drivers.claude_code import ClaudeCodeDriver

    driver = ClaudeCodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-missing", session_is_continuation=True,
    )

    assert result.success is False
    assert result.reason == "session_state_lost"


@pytest.mark.asyncio
async def test_claude_no_session_id_unchanged(monkeypatch, tmp_path):
    """Omitting session_id must behave exactly like today: no state file, no -r flag."""
    import os

    from agentcore.drivers.claude_code import ClaudeCodeDriver

    captured_cmd = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured_cmd["argv"] = argv
        return FakeProc(
            ['{"type":"result","subtype":"success","result":"ok","usage":{"input_tokens":1,"output_tokens":1}}'],
            returncode=0,
        )

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)

    driver = ClaudeCodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert result.success is True
    assert "-r" not in captured_cmd["argv"]
    assert not os.path.isdir(os.path.join(str(tmp_path), ".agent-state", "claude-code", "sessions"))

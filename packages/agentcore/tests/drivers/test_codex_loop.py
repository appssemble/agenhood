import asyncio

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody

pytestmark = pytest.mark.unit

LIMITS = ResolvedLimits(max_iterations=10, max_tokens=100000, timeout_seconds=60)


def cfg(model="gpt-5-codex"):
    return AgentConfig(driver="codex", model=model, system_prompt="P", tools=[])


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
    async def fake_exec(*args, **kwargs):
        proc.returncode = None
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_terminate_failure_during_cleanup_does_not_mask_error(monkeypatch, tmp_path):
    # Reproduces tsk_01kvsjy…: an exception in the read loop sends control to the
    # except handler, whose first act is proc.terminate(); when that raises EPERM
    # (root lacks CAP_KILL for the agent-uid child) it must NOT escape/mask — the
    # task should fail cleanly as codex_error carrying the real cause.
    from agentcore.drivers.codex import CodexDriver

    class BoomStdout:
        async def readline(self):
            raise RuntimeError("stream blew up")

    class KillProc:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = BoomStdout()
            self.returncode = None

        def terminate(self):
            raise PermissionError(1, "Operation not permitted")

        async def wait(self):
            self.returncode = -15
            return -15

    patch_proc(monkeypatch, KillProc())
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success is False
    assert result.reason == "codex_error"
    final = events[-1][1]
    assert final["to"] == "failed"
    assert final["error"]["code"] == "codex_error"
    assert "stream blew up" in final["error"]["message"]


@pytest.mark.asyncio
async def test_success_emits_result_and_tokens(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    lines = [
        '{"type":"item.completed","item":{"type":"agent_message","text":"all done"}}\n',
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n',
    ]
    proc = FakeProc(lines, returncode=0)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="do it"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert result.success
    assert result.output == "all done"
    assert proc.stdin.data == b"do it"
    types = [t for t, _ in events]
    assert types[0] == "status_change"
    assert "codex_event" in types
    assert "token_update" in types
    tok = [p for t, p in events if t == "token_update"][-1]
    assert tok == {"tokens_in": 100, "tokens_out": 20}
    assert events[-1][1]["to"] == "completed"


@pytest.mark.asyncio
async def test_turn_failed_nonzero_exit_fails(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    lines = ['{"type":"turn.failed","error":{"message":"model exploded"}}\n']
    proc = FakeProc(lines, returncode=1)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "model exploded"
    assert events[-1][1]["to"] == "failed"
    assert events[-1][1]["error"]["message"] == "model exploded"


@pytest.mark.asyncio
async def test_cancellation_returns_cancelled(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    proc = FakeProc(["line\n"] * 100, returncode=0)
    patch_proc(monkeypatch, proc)
    cancel = asyncio.Event()
    cancel.set()
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=cancel, workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "cancelled"
    assert events[-1][1]["to"] == "cancelled"


@pytest.mark.asyncio
async def test_timeout_returns_timeout(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    proc = FakeProc(["line\n"] * 100, returncode=0)
    patch_proc(monkeypatch, proc)
    events, emit = collector()
    limits = ResolvedLimits(max_iterations=10, max_tokens=10**9, timeout_seconds=0)

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=limits,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "timeout"
    assert events[-1][1]["to"] == "timed_out"


@pytest.mark.asyncio
async def test_missing_binary_reports_unavailable(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    async def boom(*args, **kwargs):
        raise FileNotFoundError("codex")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "codex_unavailable"
    assert events[-1][1]["error"]["code"] == "codex_unavailable"


@pytest.mark.asyncio
async def test_oauth_subscription_writes_auth_json(monkeypatch, tmp_path):
    import json as _json
    from pathlib import Path

    from agentcore.drivers.codex import CodexDriver, codex_home

    line = '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
    proc = FakeProc([line], returncode=0)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="access-tok", emit=emit, cancel=asyncio.Event(),
        credential_kind="oauth_subscription",
        credential_meta={"refresh_token": "ref", "account_id": "acct"},
        workspace=str(tmp_path),
    )

    auth = Path(codex_home(str(tmp_path))) / "auth.json"
    assert auth.exists()
    data = _json.loads(auth.read_text())
    assert data["tokens"]["access_token"] == "access-tok"
    assert data["tokens"]["refresh_token"] == "ref"


@pytest.mark.asyncio
async def test_stdin_broken_pipe_fails_cleanly(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    class BrokenStdin(FakeStdin):
        async def drain(self):
            raise BrokenPipeError("codex died")

    proc = FakeProc([], returncode=1)
    proc.stdin = BrokenStdin()
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "codex_error"
    assert events[-1][1]["to"] == "failed"
    assert events[-1][1]["error"]["code"] == "codex_error"


@pytest.mark.asyncio
async def test_nonzero_exit_without_error_event(monkeypatch, tmp_path):
    from agentcore.drivers.codex import CodexDriver

    proc = FakeProc([], returncode=2)
    patch_proc(monkeypatch, proc)
    events, emit = collector()

    result = await CodexDriver().run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert not result.success
    assert result.reason == "codex exited 2"
    assert events[-1][1]["to"] == "failed"
    assert events[-1][1]["error"]["code"] == "codex_nonzero_exit"


def test_codex_self_registers():
    import agentcore.drivers.codex  # noqa: F401
    from agentcore.drivers.base import DRIVERS

    assert "codex" in DRIVERS


def test_codex_capabilities_and_template():
    import agentcore.drivers.codex  # noqa: F401
    from agentcore.drivers.base import DRIVERS

    d = DRIVERS["codex"]
    assert d.capabilities.supports_tools is False
    assert d.capabilities.supports_structured_output is False
    assert d.capabilities.supports_cancel is True
    assert d.capabilities.requires_image_feature is None
    assert d.default_template.driver == "codex"
    assert d.default_template.available_tools == []
    assert d.default_template.tools_user_editable is False
    assert d.default_template.supports_context is False

from __future__ import annotations

import asyncio

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody

pytestmark = pytest.mark.unit

LIMITS = ResolvedLimits(max_iterations=10, max_tokens=100000, timeout_seconds=60)


def cfg(model="claude-opus-4-8"):
    return AgentConfig(driver="opencode", model=model, tools=[])


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdin = None
        self.stdout = FakeStdout([ln.encode() if isinstance(ln, str) else ln for ln in lines])
        self.returncode = None
        self._final_rc = returncode

    def terminate(self):
        self.returncode = -15

    async def wait(self):
        self.returncode = self._final_rc
        return self._final_rc


@pytest.mark.asyncio
async def test_opencode_session_first_turn_writes_state(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver

    captured_cmd = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured_cmd["argv"] = argv
        return FakeProc(
            ['{"type":"text","sessionID":"ses_1","part":{"text":"hi"}}'], returncode=0
        )

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    # ensure_agent_dir is left real (not stubbed): it's a plain os.makedirs in
    # non-root test environments, and session_state.write_session_state relies
    # on it to actually create the on-disk sessions/ dir on a session's first
    # turn (same fix as test_claude_code_loop.py's patch_proc, task 3).

    driver = OpencodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hello"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-1", session_is_continuation=False,
    )

    assert result.success is True
    assert "-s" not in captured_cmd["argv"]
    from agentcore.drivers.session_state import read_session_state
    assert read_session_state(str(tmp_path), "opencode", "sess-1") == {
        "opencode_session_id": "ses_1"
    }


@pytest.mark.asyncio
async def test_opencode_session_continuation_passes_resume_flag(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver
    from agentcore.drivers.session_state import write_session_state

    write_session_state(str(tmp_path), "opencode", "sess-2", {"opencode_session_id": "ses_1"})
    captured_cmd = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured_cmd["argv"] = argv
        return FakeProc(
            ['{"type":"text","sessionID":"ses_1","part":{"text":"ok"}}'], returncode=0
        )

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)

    driver = OpencodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="continue"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-2", session_is_continuation=True,
    )

    assert result.success is True
    assert captured_cmd["argv"][captured_cmd["argv"].index("-s") + 1] == "ses_1"


@pytest.mark.asyncio
async def test_opencode_session_missing_state_fails_fast(tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver

    driver = OpencodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-missing", session_is_continuation=True,
    )

    assert result.success is False
    assert result.reason == "session_state_lost"


@pytest.mark.asyncio
async def test_opencode_no_session_id_unchanged(monkeypatch, tmp_path):
    import os

    from agentcore.drivers.opencode import OpencodeDriver

    captured_cmd = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured_cmd["argv"] = argv
        return FakeProc(
            ['{"type":"text","sessionID":"ses_x","part":{"text":"hi"}}'], returncode=0
        )

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)

    driver = OpencodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert result.success is True
    assert "-s" not in captured_cmd["argv"]
    assert not os.path.isdir(os.path.join(str(tmp_path), ".agent-state", "opencode", "sessions"))


# ---- free-plan rate-limit hang detection (opencode logs the error but never
# ---- exits or emits stdout; the driver must tail the log and fail fast) -----

_RATE_LIMIT_LOG_LINE = (
    'timestamp=2026-07-13T13:16:47.743Z level=ERROR run=ee249358 '
    'message="stream error" providerID=opencode modelID=deepseek-v4-flash-free '
    'session.id=ses_x small=false agent=build mode=primary '
    'error.error="AI_APICallError: Rate limit exceeded. Please try again later."'
)


def test_scan_opencode_log_detects_rate_limit():
    from agentcore.drivers.opencode import scan_opencode_log_for_fatal
    assert scan_opencode_log_for_fatal(_RATE_LIMIT_LOG_LINE + "\n") == "rate_limited"


def test_scan_opencode_log_ignores_normal_lines():
    from agentcore.drivers.opencode import scan_opencode_log_for_fatal
    normal = (
        'timestamp=... level=INFO message=loop session.id=ses_x step=0\n'
        'timestamp=... level=INFO message=stream providerID=opencode\n'
    )
    assert scan_opencode_log_for_fatal(normal) is None


def test_opencode_log_path_matches_xdg_layout(tmp_path):
    from agentcore.drivers.opencode import opencode_log_path
    p = opencode_log_path(str(tmp_path))
    assert p.endswith("/.agent-state/opencode/data/opencode/log/opencode.log")


class _SilentStdoutThenLog:
    """Mimics opencode on a rate limit: emits NOTHING on stdout and never
    returns EOF, but appends the rate-limit error to its log on first read."""

    def __init__(self, log_path, line):
        self._first = True
        self._log_path = log_path
        self._line = line
        self._never = asyncio.Event()

    async def readline(self):
        if self._first:
            self._first = False
            import os
            os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
            with open(self._log_path, "a") as f:
                f.write(self._line + "\n")
        await self._never.wait()  # never returns -> wait_for times out every 1s


class _HangingProc:
    def __init__(self, stdout):
        self.stdin = None
        self.stdout = stdout
        self.returncode = None

    def terminate(self):
        self.returncode = -15

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_opencode_rate_limit_hang_fails_fast(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver, opencode_log_path

    log_path = opencode_log_path(str(tmp_path))

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        return _HangingProc(_SilentStdoutThenLog(log_path, _RATE_LIMIT_LOG_LINE))

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)

    driver = OpencodeDriver()
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="hi"), config=cfg(), limits=LIMITS,
        credential="cred", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), session_id="sess-rl", session_is_continuation=False,
    )

    assert result.success is False
    assert result.reason == "rate_limited"
    # a terminal failed status_change was emitted with a clear code
    finals = [p for t, p in events if t == "status_change" and p.get("to") == "failed"]
    assert finals and finals[-1]["error"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_run_materializes_configured_system_prompt(monkeypatch, tmp_path):
    import json as _json
    import pathlib as _pathlib

    from agentcore.drivers.opencode import OpencodeDriver, opencode_config_path

    async def fake_spawn(*args, **kwargs):
        return FakeProc([], returncode=0)

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    events, emit = collector()
    config = AgentConfig(
        driver="opencode", model="claude-opus-4-8",
        system_prompt="Answer in French.", tools=[],
    )
    await OpencodeDriver().run(
        task=TaskBody(prompt="x"), config=config, limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )
    cfg_file = _pathlib.Path(opencode_config_path(str(tmp_path)))
    data = _json.loads(cfg_file.read_text())
    assert len(data["instructions"]) == 1
    assert _pathlib.Path(data["instructions"][0]).read_text() == "Answer in French."


# ---------------------------------------------------------------------------
# Task 6: structured output — prompt-injection + validate-and-retry loop
# (opencode has no native schema flag; the shared backstop is the sole
# enforcement mechanism)
# ---------------------------------------------------------------------------


def patch_procs(monkeypatch, procs):
    """Each spawn_untrusted call consumes the next FakeProc; records argv."""
    calls = []

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        calls.append(argv)
        proc = procs.pop(0)
        proc.returncode = None
        return proc

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    return calls


STRUCT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def structured_task():
    return TaskBody(
        prompt="answer me",
        output={"type": "structured", "schema": STRUCT_SCHEMA},
    )


def opencode_text_line(text, session_id="ses_1"):
    import json as _json

    return _json.dumps(
        {"type": "text", "part": {"text": text}, "sessionID": session_id}
    ) + "\n"


@pytest.mark.asyncio
async def test_structured_valid_first_attempt(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver

    proc = FakeProc([opencode_text_line('{"answer": "42"}')])
    calls = patch_procs(monkeypatch, [proc])
    events, emit = collector()

    result = await OpencodeDriver().run(
        task=structured_task(), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert result.success is True
    assert result.output == {"answer": "42"}
    # schema instructions rode along in the positional prompt
    assert any("## Output" in str(a) for a in calls[0])
    completed = [p for t, p in events if t == "status_change" and p["to"] == "completed"]
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_structured_retries_via_session_resume(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver

    bad = FakeProc([opencode_text_line("not json")])
    good = FakeProc([opencode_text_line('{"answer": "42"}')])
    calls = patch_procs(monkeypatch, [bad, good])
    events, emit = collector()

    result = await OpencodeDriver().run(
        task=structured_task(), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )

    assert result.success is True
    assert len(calls) == 2
    assert "-s" in calls[1] and "ses_1" in calls[1]
    assert any("Invalid output" in str(a) for a in calls[1])
    warns = [p for t, p in events if t == "log" and p["message"] == "structured_output_invalid"]
    assert len(warns) == 1


@pytest.mark.asyncio
async def test_structured_fails_after_max_attempts(monkeypatch, tmp_path):
    from agentcore.drivers.opencode import OpencodeDriver
    from agentcore.structured_output import MAX_ATTEMPTS

    procs = [FakeProc([opencode_text_line("nope")]) for _ in range(MAX_ATTEMPTS)]
    calls = patch_procs(monkeypatch, list(procs))
    events, emit = collector()

    result = await OpencodeDriver().run(
        task=structured_task(), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )
    assert result.success is False
    assert result.reason == "invalid_structured_output"
    assert len(calls) == MAX_ATTEMPTS
    failed = [p for t, p in events if t == "status_change" and p["to"] == "failed"]
    assert failed[-1]["error"]["code"] == "invalid_structured_output"


def test_opencode_supports_structured_output():
    from agentcore.drivers.opencode import OpencodeDriver

    assert OpencodeDriver.capabilities.supports_structured_output is True

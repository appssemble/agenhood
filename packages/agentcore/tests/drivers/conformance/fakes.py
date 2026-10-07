"""Shared test fakes and constants for the driver conformance suite."""
from __future__ import annotations

import asyncio
from typing import Any

from agentcore.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Canonical test secrets
# ---------------------------------------------------------------------------

CRED = "sk-ant-testcred"
REFRESH = "refresh-testtoken"
ACCOUNT = "acct-test"
MCP_SECRET = "mcp-secret-xyz"


def SUBS(workspace: str) -> dict[str, str]:
    """Return the normalisation map used by golden-file assertions."""
    return {
        workspace: "<WS>",
        CRED: "<CRED>",
        REFRESH: "<REFRESH>",
        ACCOUNT: "<ACCOUNT>",
        MCP_SECRET: "<MCP_SECRET>",
    }


# ---------------------------------------------------------------------------
# FakeStdin / FakeStdout / FakeProc — lifted verbatim from
# tests/drivers/test_claude_code_loop.py (lines 25-61)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ScriptedLLM — lifted verbatim from tests/drivers/test_vanilla_loop.py (lines 17-35)
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Returns canned LLMResponses in order; records the calls it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, *, model, system, messages, tools, max_tokens, credential):
        self.calls.append(
            {"model": model, "system": system, "messages": list(messages),
             "tools": tools, "max_tokens": max_tokens}
        )
        if self._responses:
            return self._responses.pop(0)
        # Default: never-ending text turns (used for limit tests).
        return LLMResponse(
            content=[{"type": "text", "text": "thinking"}],
            tokens_in=10, tokens_out=10, stop_reason="end_turn",
        )


# ---------------------------------------------------------------------------
# patch_proc — patches agentcore.sandbox.spawn_untrusted + ensure_agent_dir
# ---------------------------------------------------------------------------


def patch_proc(monkeypatch, proc: FakeProc) -> None:
    async def fake_spawn(argv, *, cwd, env, **kwargs):
        proc.returncode = None
        return proc

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", fake_spawn)
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# FakeAppServer / patch_app_server: codex runs on `codex app-server`, so its
# scenarios replay JSON-RPC notifications instead of exec JSONL.
# ---------------------------------------------------------------------------


class FakeAppServer:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.alive = True

    async def request(self, method, params, timeout=None):  # noqa: ASYNC109
        if method == "thread/start":
            return {"thread": {"id": "thr_conf"}}
        return {}

    async def next_message(self, timeout):  # noqa: ASYNC109
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(0)
        return None

    def terminate(self):
        self.alive = False

    def abort(self):
        self.alive = False

    async def close(self, timeout=5.0):  # noqa: ASYNC109
        self.alive = False


def patch_app_server(monkeypatch, messages=()) -> None:
    async def fake_start(cmd, *, cwd, env):
        return FakeAppServer(messages)

    monkeypatch.setattr("agentcore.drivers.codex.start_app_server", fake_start)


# ---------------------------------------------------------------------------
# collector — captures (event_type, payload) tuples
# ---------------------------------------------------------------------------


def collector():
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit

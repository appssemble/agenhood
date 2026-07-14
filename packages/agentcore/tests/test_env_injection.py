from __future__ import annotations

import asyncio

import pytest

from agentcore import sandbox
from agentcore.drivers import claude_code, codex, opencode
from agentcore.tools.base import ToolContext


def test_tool_context_env_defaults_empty() -> None:
    ctx = ToolContext(workspace="/w", cancel=asyncio.Event())
    assert ctx.env == {}


def test_build_child_env_applies_user_extra() -> None:
    env = sandbox.build_child_env({"MY_VAR": "x"})
    assert env["MY_VAR"] == "x"


def test_claude_credential_wins_over_user_env() -> None:
    base = sandbox.build_child_env({"ANTHROPIC_API_KEY": "user-supplied"})
    env = claude_code.build_env(
        base, credential="real-key", credential_kind="api_key", home="/h"
    )
    assert env["ANTHROPIC_API_KEY"] == "real-key"
    assert env["HOME"] == "/h"  # user env can't move the driver HOME either


def test_codex_home_wins_over_user_env() -> None:
    base = sandbox.build_child_env({"CODEX_API_KEY": "user"})
    env = codex.build_env(
        base, credential="real", credential_kind="api_key", codex_home="/ch"
    )
    assert env["CODEX_API_KEY"] == "real"
    assert env["CODEX_HOME"] == "/ch"


def test_opencode_provider_key_wins_over_user_env() -> None:
    base = sandbox.build_child_env({"ANTHROPIC_API_KEY": "user"})
    env = opencode.build_env(
        base, provider="anthropic", credential="real", credential_kind="api_key"
    )
    assert env["ANTHROPIC_API_KEY"] == "real"


@pytest.mark.asyncio
async def test_shell_tool_passes_ctx_env(monkeypatch) -> None:
    from agentcore.tools.shell import BashTool

    captured: dict = {}

    async def fake_spawn(argv, *, cwd, env, **kwargs):
        captured["env"] = env

        class P:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return P()

    monkeypatch.setattr(sandbox, "spawn_untrusted", fake_spawn)
    ctx = ToolContext(workspace="/tmp", cancel=asyncio.Event(), env={"MY_VAR": "x"})
    await BashTool().run({"command": "true"}, ctx)
    assert captured["env"]["MY_VAR"] == "x"

"""Claude Code driver — shells out to Anthropic's official ``claude`` CLI (``-p``).

Near-twin of the codex driver (spec §3.5.2 best-effort semantics): only
``timeout_seconds`` + cancellation bound it. Runs ``claude -p --output-format
stream-json`` with the prompt on stdin, forwards the JSONL events, and extracts
the final ``result`` text as the task result. Self-registers via register().

Auth: ``ANTHROPIC_API_KEY`` for the api-key path; ``CLAUDE_CODE_OAUTH_TOKEN`` for
``oauth_subscription`` (a long-lived ``claude setup-token`` value, or a
control-plane-refreshed access token — both injected identically). HOME is
redirected under the writable workspace (the container $HOME is not writable by
the dropped child — the same constraint codex solves with CODEX_HOME).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from agentcore import sandbox
from agentcore.drivers.base import (
    DriverCapabilities,
    DriverTemplate,
    EmitFn,
    _coerce_token_pair,
    register,
)
from agentcore.drivers.cli_stream import classify_json_line
from agentcore.drivers.mcp_config import render_claude_mcp_json
from agentcore.drivers.skills_md import write_skills
from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimMcpServer,
    ShimSkill,
    TaskBody,
    TaskResult,
)


def model_arg(model: str) -> str:
    """The ``--model`` argument claude expects (a bare Anthropic model id)."""
    if model.startswith("anthropic/"):
        return model.split("/", 1)[1]
    return model


def claude_home(workspace: str) -> str:
    """Writable $HOME under the agent-owned .agent-state tree."""
    return str(Path(workspace) / ".agent-state" / "claude-code")


def skills_dir(workspace: str) -> str:
    """Claude's skill discovery dir: ``$HOME/.claude/skills`` (HOME redirected)."""
    return str(Path(claude_home(workspace)) / ".claude" / "skills")


def mcp_config_path(workspace: str) -> str:
    """Per-task hermetic MCP config under the redirected $HOME/.claude."""
    return str(Path(claude_home(workspace)) / ".claude" / "mcp.json")


def build_command(
    *, workspace: str, model: str, mcp_config: str | None = None
) -> list[str]:
    """Build the ``claude -p`` invocation (prompt is fed on stdin)."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--dangerously-skip-permissions",
    ]
    if mcp_config:
        cmd += ["--strict-mcp-config", "--mcp-config", mcp_config]
    return cmd


def build_env(
    base_env: dict[str, str],
    *,
    credential: str,
    credential_kind: str,
    home: str,
) -> dict[str, str]:
    """Redirect HOME; inject the right credential env var per auth path.

    api_key            -> ANTHROPIC_API_KEY
    oauth_subscription -> CLAUDE_CODE_OAUTH_TOKEN

    An unrecognized ``credential_kind`` raises ValueError: claude-code routes
    both auth paths through this function, so a silent no-op would surface later
    as a confusing CLI auth failure.
    """
    env = dict(base_env)
    env["HOME"] = home
    if credential_kind == "api_key":
        env["ANTHROPIC_API_KEY"] = credential
    elif credential_kind == "oauth_subscription":
        env["CLAUDE_CODE_OAUTH_TOKEN"] = credential
    else:
        raise ValueError(f"unknown credential_kind: {credential_kind!r}")
    return env


def parse_claude_line(line: str) -> tuple[str, object | None]:
    """Classify one line of claude stream-json output.

    Returns ('event', dict) for JSON lines, ('stdout', str) for plain text,
    ('ignore', None) for blank lines.
    """
    return classify_json_line(line)


def result_text(event: dict[str, Any]) -> str | None:
    """Final assistant text from a successful ``result`` event, else None."""
    if event.get("type") == "result" and event.get("subtype") == "success":
        r = event.get("result")
        if isinstance(r, str):
            return r
    return None


def result_usage(event: dict[str, Any]) -> tuple[int, int] | None:
    """``(input, output)`` token counts from a ``result`` event's usage.

    Maps input_tokens/output_tokens to tokens_in/tokens_out; cache tokens are
    dropped (parity with codex/opencode/vanilla).
    """
    if event.get("type") != "result":
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    return _coerce_token_pair(usage.get("input_tokens"), usage.get("output_tokens"))


def result_error(event: dict[str, Any]) -> str | None:
    """Error message from a failed ``result`` event, else None."""
    if event.get("type") == "result" and event.get("is_error"):
        for key in ("error", "result"):
            v = event.get(key)
            if isinstance(v, str) and v:
                return v
        return "claude reported an error"
    return None


_CLAUDE_PROMPT = (
    "You are Claude Code, an autonomous coding agent. Complete the task in the "
    "workspace and report concisely when finished."
)


class ClaudeCodeDriver:
    """Driver that shells out to the ``claude`` binary in ``-p`` mode (spec §3)."""

    name = "claude-code"
    capabilities = DriverCapabilities(
        supports_tools=False,
        supports_structured_output=False,
        supports_cancel=True,
        requires_image_feature=None,
        supports_mcp=True,
    )
    default_template = DriverTemplate(
        driver="claude-code",
        default_system_prompt=_CLAUDE_PROMPT,
        available_tools=[],  # claude owns its tools; list is empty
        tools_user_editable=False,
        supports_context=False,
    )

    async def run(
        self,
        *,
        task: TaskBody,
        config: AgentConfig,
        limits: ResolvedLimits,
        credential: str,
        emit: EmitFn,
        cancel: asyncio.Event,
        credential_kind: str = "api_key",
        credential_meta: dict[str, Any] | None = None,
        workspace: str = "/workspace",
        skills: list[ShimSkill] | None = None,
        mcp_servers: list[ShimMcpServer] | None = None,
    ) -> TaskResult:
        Path(workspace).mkdir(parents=True, exist_ok=True)

        await emit(
            "status_change",
            {"from": "pending", "to": "running", "result": None, "error": None},
        )

        home = claude_home(workspace)
        sandbox.ensure_agent_dir(home)

        # Materialize skills into the discovery dir (best-effort: a failure must
        # never change the task outcome — skills are an enhancement).
        try:
            sandbox.ensure_agent_dir(skills_dir(workspace))
            names = await write_skills(skills_dir(workspace), skills or [])
            if names:
                await emit("log", {"level": "info", "message": "skills_materialized",
                                   "data": {"count": len(names), "names": names}})
        except Exception as exc:  # noqa: BLE001 — skills are best-effort
            await emit("log", {"level": "warn", "message": "skills_error",
                               "data": {"error": str(exc)}})

        # Materialize MCP config (best-effort). Only pass --mcp-config when servers
        # are present, so a no-MCP run stays a clean invocation.
        mcp_path: str | None = None
        if mcp_servers:
            try:
                path = Path(mcp_config_path(workspace))
                sandbox.ensure_agent_dir(str(path.parent))
                path.unlink(missing_ok=True)
                path.write_text(json.dumps(render_claude_mcp_json(mcp_servers)))
                os.chmod(path, 0o600)
                sandbox.chown_to_agent(str(path))
                mcp_path = str(path)
                await emit("log", {"level": "info", "message": "mcp_materialized",
                                   "data": {"count": len(mcp_servers),
                                            "names": [s.name for s in mcp_servers]}})
            except Exception as exc:  # noqa: BLE001 — MCP is best-effort
                await emit("log", {"level": "warn", "message": "mcp_error",
                                   "data": {"error": str(exc)}})

        cmd = build_command(
            workspace=workspace, model=model_arg(config.model), mcp_config=mcp_path
        )
        env = build_env(
            sandbox.build_child_env(),
            credential=credential,
            credential_kind=credential_kind,
            home=home,
        )

        try:
            proc = await sandbox.spawn_untrusted(
                cmd,
                cwd=workspace,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {
                        "code": "claude_code_unavailable",
                        "message": "claude binary not found",
                    },
                },
            )
            return TaskResult(success=False, reason="claude_code_unavailable")

        start = time.monotonic()
        last_text: str | None = None
        error_msg: str | None = None
        tokens_in = 0
        tokens_out = 0
        try:
            if proc.stdin is not None:
                proc.stdin.write(task.prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            assert proc.stdout is not None
            while True:
                if cancel.is_set():
                    sandbox.terminate(proc)
                    await emit(
                        "status_change",
                        {"from": "running", "to": "cancelled", "result": None, "error": None},
                    )
                    return TaskResult(success=False, reason="cancelled")

                if time.monotonic() - start >= limits.timeout_seconds:
                    sandbox.terminate(proc)
                    await emit(
                        "log", {"level": "warn", "message": "wall-clock timeout", "data": {}}
                    )
                    await emit(
                        "status_change",
                        {
                            "from": "running",
                            "to": "timed_out",
                            "result": None,
                            "error": {"code": "timeout", "message": "wall-clock timeout"},
                        },
                    )
                    return TaskResult(success=False, reason="timeout")

                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except TimeoutError:
                    if proc.returncode is not None:
                        break
                    continue

                if not raw:
                    break

                line = raw.decode("utf-8", "replace").rstrip("\n")
                kind, value = parse_claude_line(line)
                if kind == "event":
                    assert isinstance(value, dict)
                    await emit("claude_event", {"raw": value})
                    text = result_text(value)
                    if text is not None:
                        last_text = text
                    err = result_error(value)
                    if err is not None:
                        error_msg = err
                    usage = result_usage(value)
                    if usage is not None:
                        tokens_in += usage[0]
                        tokens_out += usage[1]
                        await emit(
                            "token_update",
                            {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        )
                elif kind == "stdout":
                    assert isinstance(value, str)
                    await emit("claude_stdout", {"line": value})

            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception as exc:  # defensive: also catches a startup BrokenPipeError
            sandbox.terminate(proc)
            await emit(
                "status_change",
                {
                    "from": "running",
                    "to": "failed",
                    "result": None,
                    "error": {"code": "claude_code_error", "message": str(exc)},
                },
            )
            return TaskResult(success=False, reason="claude_code_error")

        if rc == 0 and error_msg is None:
            result = {"success": True, "output": last_text or ""}
            await emit(
                "status_change",
                {"from": "running", "to": "completed", "result": result, "error": None},
            )
            return TaskResult(success=True, output=last_text or "")

        message = error_msg or f"claude exited {rc}"
        await emit(
            "status_change",
            {
                "from": "running",
                "to": "failed",
                "result": None,
                "error": {
                    "code": "claude_code_error" if error_msg else "claude_code_nonzero_exit",
                    "message": message,
                },
            },
        )
        return TaskResult(success=False, reason=message)


register(ClaudeCodeDriver())

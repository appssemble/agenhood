from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

from agentcore import sandbox
from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms, register

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
MAX_OUTPUT_BYTES = 256 * 1024


def _truncate(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_OUTPUT_BYTES:
        return text
    return raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n[...truncated...]"


async def _run_subprocess(
    argv: list[str], cwd: str, timeout_secs: int, env: dict[str, str] | None = None
) -> tuple[int, str, str, bool]:
    """Run argv as the unprivileged agent, returning (rc, stdout, stderr, timed_out)."""
    proc = await sandbox.spawn_untrusted(
        argv,
        cwd=cwd,
        env=sandbox.build_child_env(env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_secs)
    except TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        timed_out,
    )


class BashTool:
    spec = ToolSpec(
        name="bash",
        description=(
            "Run a bash command in /workspace. Captures stdout, stderr, exit code. "
            "Default 60s timeout, max 600s. Killed on timeout."
        ),
        input_schema={
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "seconds, max 600"},
            },
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            command = input["command"]
        except KeyError:
            return ToolResult(
                ok=False, content="missing required field: command", duration_ms=_ms(start)
            )
        try:
            timeout = min(int(input.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)
        except (TypeError, ValueError):
            return ToolResult(
                ok=False, content="timeout must be an integer", duration_ms=_ms(start)
            )
        cwd = os.path.realpath(ctx.workspace)
        code, out, err, timed_out = await _run_subprocess(
            ["bash", "-lc", command], cwd, timeout, env=ctx.env
        )
        body_parts = []
        if out:
            body_parts.append(f"stdout:\n{out}")
        if err:
            body_parts.append(f"stderr:\n{err}")
        if timed_out:
            body_parts.append(f"command timed out after {timeout}s and was killed")
        else:
            body_parts.append(f"exit code: {code}")
        content = _truncate("\n".join(body_parts))
        return ToolResult(
            ok=(code == 0 and not timed_out), content=content, duration_ms=_ms(start)
        )


class PythonTool:
    spec = ToolSpec(
        name="python",
        description=(
            "Run a Python 3 snippet in an isolated subprocess (no pip install). "
            "stdout/stderr captured."
        ),
        input_schema={
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer"},
            },
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            code_arg = input["code"]
        except KeyError:
            return ToolResult(
                ok=False, content="missing required field: code", duration_ms=_ms(start)
            )
        try:
            timeout = min(int(input.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)
        except (TypeError, ValueError):
            return ToolResult(
                ok=False, content="timeout must be an integer", duration_ms=_ms(start)
            )
        cwd = os.path.realpath(ctx.workspace)
        code, out, err, timed_out = await _run_subprocess(
            [sys.executable, "-c", code_arg], cwd, timeout, env=ctx.env
        )
        body_parts = []
        if out:
            body_parts.append(f"stdout:\n{out}")
        if err:
            body_parts.append(f"stderr:\n{err}")
        if timed_out:
            body_parts.append(f"snippet timed out after {timeout}s and was killed")
        content = _truncate("\n".join(body_parts) or "(no output)")
        return ToolResult(
            ok=(code == 0 and not timed_out), content=content, duration_ms=_ms(start)
        )


register(BashTool())
register(PythonTool())

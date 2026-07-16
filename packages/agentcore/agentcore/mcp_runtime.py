"""MCP runtime for the vanilla driver: remote streamable-HTTP servers only.

One McpRuntime per task run. Remote tools surface as McpToolAdapter objects
satisfying the Tool protocol, named ``mcp__<server>__<tool>`` — they join the
loop's per-run tool table and are otherwise indistinguishable from built-ins.
Failures never raise out of this module: connect failures land in ``errors``,
call failures return ``is_error`` ToolResults.

Each server's transport lives in a dedicated worker task: the SDK's streamable
HTTP transport is an anyio task group whose cancel scope must be entered and
exited by the same task, and which cancels its host task on transport failure
(the real error only surfaces as an ExceptionGroup when the context unwinds).
Confining that lifecycle to one task per server keeps a bad server from
cancelling its siblings and lets ``close()`` unwind safely from any task.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import ListToolsResult

from agentcore.models import ShimMcpServer
from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_CALL_TIMEOUT = 60.0

# Mirrors the SDK's recommended client defaults (30s ops, long SSE reads);
# our own asyncio timeouts govern connect/call deadlines on top.
_HTTP_TIMEOUT = httpx.Timeout(30.0, read=300.0)

_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _sanitize(part: str) -> str:
    return _NAME_SANITIZE_RE.sub("-", part).strip("-")


def _tool_name(server: str, tool: str) -> str:
    """Anthropic tool names must match [a-zA-Z0-9_-]{1,128}."""
    return f"mcp__{_sanitize(server)}__{_sanitize(tool)}"[:128]


def _headers(s: ShimMcpServer) -> dict[str, str] | None:
    """Same auth mapping as the opencode/claude MCP config renderers."""
    if s.auth_type == "bearer" and s.secret:
        return {"Authorization": f"Bearer {s.secret}"}
    if s.auth_type == "header" and s.auth_header_name and s.secret:
        return {s.auth_header_name: s.secret}
    return None


def _describe_error(e: BaseException) -> str:
    """Flatten exception groups (the transport task group's failure shape)."""
    if isinstance(e, BaseExceptionGroup):
        return "; ".join(dict.fromkeys(_describe_error(x) for x in e.exceptions))
    return str(e) or type(e).__name__


def _content_to_text(blocks: list[Any]) -> str:
    """Map MCP result content to plain text (text-only loop in v1)."""
    parts: list[str] = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            try:
                parts.append(json.dumps(block.model_dump(mode="json")))
            except Exception:  # noqa: BLE001 — last-resort repr
                parts.append(repr(block))
    return "\n".join(parts)


class _Connection:
    """Owns one server's transport lifecycle inside a dedicated task."""

    def __init__(self, server: ShimMcpServer, connect_timeout: float) -> None:
        self._server = server
        self._connect_timeout = connect_timeout
        self.session: ClientSession | None = None
        self.listed: ListToolsResult | None = None
        self.error: str | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def open(self) -> bool:
        """Start the worker and wait for connect-or-fail. Returns success."""
        self._task = asyncio.create_task(self._run())
        try:
            await self._ready.wait()
        except asyncio.CancelledError:
            self._stop.set()
            self._task.cancel()
            raise
        return self.error is None

    async def _run(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(self._connect_timeout):
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=_headers(self._server),
                            timeout=_HTTP_TIMEOUT,
                            follow_redirects=True,
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(self._server.url, http_client=client)
                    )
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self.listed = await session.list_tools()
                self.session = session
                self._ready.set()
                # Hold the transport open (its cancel scope must exit in this
                # task) until close() signals shutdown.
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 — includes the transport's
            # cancel-scope CancelledError; the real cause is the unwound group.
            if self.error is None:
                self.error = _describe_error(e)
        finally:
            self.session = None
            self._ready.set()

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            task, self._task = self._task, None
            try:
                await task
            except BaseException:  # noqa: BLE001 — teardown must never raise
                pass


class McpToolAdapter:
    """A remote MCP tool presented through the local Tool protocol."""

    def __init__(
        self, runtime: McpRuntime, session_key: str, remote_name: str, spec: ToolSpec
    ) -> None:
        self._runtime = runtime
        self._session_key = session_key
        self._remote_name = remote_name
        self.spec = spec

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self._runtime.call(self._session_key, self._remote_name, input)


class McpRuntime:
    def __init__(
        self,
        connect_timeout: float | None = None,
        call_timeout: float | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout if connect_timeout is not None else float(
            os.environ.get("MCP_CONNECT_TIMEOUT_SECONDS", DEFAULT_CONNECT_TIMEOUT)
        )
        self._call_timeout = call_timeout if call_timeout is not None else float(
            os.environ.get("MCP_CALL_TIMEOUT_SECONDS", DEFAULT_CALL_TIMEOUT)
        )
        self._connections: dict[str, _Connection] = {}
        self._adapters: list[McpToolAdapter] = []
        self.errors: dict[str, str] = {}
        self.skipped_tools: list[str] = []

    async def connect(self, servers: list[ShimMcpServer]) -> None:
        await asyncio.gather(*(self._connect_one(s) for s in servers))

    async def _connect_one(self, server: ShimMcpServer) -> None:
        conn = _Connection(server, self._connect_timeout)
        ok = await conn.open()
        if not ok or conn.listed is None:
            self.errors[server.name] = conn.error or "connect failed"
            await conn.close()
            return
        self._connections[server.name] = conn
        taken = {a.spec.name for a in self._adapters}
        for t in conn.listed.tools:
            name = _tool_name(server.name, t.name)
            if name in taken:
                self.skipped_tools.append(name)
                continue
            taken.add(name)
            self._adapters.append(McpToolAdapter(
                runtime=self,
                session_key=server.name,
                remote_name=t.name,
                spec=ToolSpec(
                    name=name,
                    description=f"[{server.name}] {t.description or t.name}",
                    input_schema=t.inputSchema or {"type": "object"},
                ),
            ))

    def tools(self) -> list[McpToolAdapter]:
        return list(self._adapters)

    async def call(self, session_key: str, remote_name: str, input: dict[str, Any]) -> ToolResult:
        start = time.monotonic()
        conn = self._connections.get(session_key)
        session = conn.session if conn is not None else None
        if session is None:
            return ToolResult(
                ok=False,
                content=f"mcp server {session_key!r} is not connected",
                duration_ms=_ms(start),
            )
        try:
            async with asyncio.timeout(self._call_timeout):
                result = await session.call_tool(remote_name, arguments=input)
        except Exception as e:  # noqa: BLE001 — call failure -> error result, never raise
            return ToolResult(
                ok=False,
                content=f"mcp call {session_key}/{remote_name} failed: {_describe_error(e)}",
                duration_ms=_ms(start),
            )
        text = _content_to_text(result.content)
        if getattr(result, "isError", False):
            return ToolResult(ok=False, content=text or "mcp tool error", duration_ms=_ms(start))
        return ToolResult(ok=True, content=text, duration_ms=_ms(start))

    async def close(self) -> None:
        conns = list(self._connections.values())
        self._connections.clear()
        for conn in conns:
            await conn.close()

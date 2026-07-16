import asyncio
import socket
import threading

import pytest
import uvicorn

from agentcore.models import ShimMcpServer
from agentcore.tools.base import ToolContext

pytestmark = pytest.mark.unit

_seen_headers: dict[str, str] = {}


def _build_app():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("stub", stateless_http=True)

    @server.tool()
    def echo(text: str) -> str:
        """Echo the input back."""
        return f"echo:{text}"

    @server.tool()
    def boom() -> str:
        """Always fails."""
        raise RuntimeError("server-side failure")

    inner = server.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            _seen_headers.clear()
            _seen_headers.update(
                {k.decode(): v.decode() for k, v in scope.get("headers", [])}
            )
        await inner(scope, receive, send)

    return app


@pytest.fixture(scope="module")
def mcp_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(_build_app(), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    import time
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise TimeoutError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def _server(url, name="stub", auth_type="none", secret="", header=""):
    return ShimMcpServer(
        name=name, url=url, auth_type=auth_type,
        secret=secret, auth_header_name=header,
    )


def _ctx(tmp_path):
    return ToolContext(workspace=str(tmp_path), cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_connect_lists_namespaced_tools(mcp_url):
    from agentcore.mcp_runtime import McpRuntime

    rt = McpRuntime()
    await rt.connect([_server(mcp_url)])
    try:
        names = [a.spec.name for a in rt.tools()]
        assert "mcp__stub__echo" in names
        assert "mcp__stub__boom" in names
        echo = next(a for a in rt.tools() if a.spec.name == "mcp__stub__echo")
        assert echo.spec.input_schema.get("type") == "object"
        assert "stub" in echo.spec.description  # server name prefixed
        assert rt.errors == {}
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_call_round_trip_and_server_error(mcp_url, tmp_path):
    from agentcore.mcp_runtime import McpRuntime

    rt = McpRuntime()
    await rt.connect([_server(mcp_url)])
    try:
        adapters = {a.spec.name: a for a in rt.tools()}
        res = await adapters["mcp__stub__echo"].run({"text": "hi"}, _ctx(tmp_path))
        assert res.ok and "echo:hi" in res.content
        res = await adapters["mcp__stub__boom"].run({}, _ctx(tmp_path))
        assert not res.ok  # isError result maps to a failed ToolResult, no raise
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_bearer_auth_header_sent(mcp_url, tmp_path):
    from agentcore.mcp_runtime import McpRuntime

    rt = McpRuntime()
    await rt.connect([_server(mcp_url, auth_type="bearer", secret="tok-123")])
    try:
        assert rt.errors == {}
        assert _seen_headers.get("authorization") == "Bearer tok-123"
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_unreachable_server_recorded_not_raised():
    from agentcore.mcp_runtime import McpRuntime

    rt = McpRuntime(connect_timeout=1.0)
    await rt.connect([_server("http://127.0.0.1:9/mcp", name="dead")])
    try:
        assert "dead" in rt.errors
        assert rt.tools() == []
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_one_bad_server_does_not_poison_good_one(mcp_url):
    from agentcore.mcp_runtime import McpRuntime

    rt = McpRuntime(connect_timeout=1.0)
    await rt.connect([
        _server("http://127.0.0.1:9/mcp", name="dead"),
        _server(mcp_url, name="live"),
    ])
    try:
        assert "dead" in rt.errors
        assert any(a.spec.name == "mcp__live__echo" for a in rt.tools())
    finally:
        await rt.close()


def test_name_sanitization_and_collision():
    from agentcore.mcp_runtime import _tool_name

    assert _tool_name("my server", "do.things") == "mcp__my-server__do-things"
    assert len(_tool_name("s" * 200, "t" * 200)) <= 128

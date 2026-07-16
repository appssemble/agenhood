# Minimal streamable-HTTP MCP server for integration tests: one echo tool.
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# FastMCP auto-enables DNS-rebinding Host-header checks whenever `host`
# defaults to 127.0.0.1 (see mcp.server.fastmcp.server.FastMCP.__init__),
# allowing only 127.0.0.1/localhost/[::1] -- which rejects every request that
# arrives with the Docker container hostname in its Host header (421
# Misdirected Request). This server is only ever reachable from the test
# Docker network, so that protection is unnecessary here.
server = FastMCP(
    "stub", stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@server.tool()
def echo(text: str) -> str:
    """Echo the input back."""
    return f"mcp-echo:{text}"


app = server.streamable_http_app()

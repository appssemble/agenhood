import pytest

pytestmark = pytest.mark.unit


def test_render_claude_mcp_json_bearer() -> None:
    from agentcore.drivers.mcp_config import render_claude_mcp_json
    from agentcore.models import ShimMcpServer

    out = render_claude_mcp_json([
        ShimMcpServer(name="gh", url="https://mcp.example/gh", auth_type="bearer", secret="t0k"),
    ])
    assert out == {
        "mcpServers": {
            "gh": {
                "type": "http",
                "url": "https://mcp.example/gh",
                "headers": {"Authorization": "Bearer t0k"},
            }
        }
    }


def test_render_claude_mcp_json_header_and_none() -> None:
    from agentcore.drivers.mcp_config import render_claude_mcp_json
    from agentcore.models import ShimMcpServer

    out = render_claude_mcp_json([
        ShimMcpServer(name="a", url="https://a", auth_type="header",
                      auth_header_name="X-Api-Key", secret="s"),
        ShimMcpServer(name="b", url="https://b", auth_type="none"),
    ])
    assert out["mcpServers"]["a"]["headers"] == {"X-Api-Key": "s"}
    assert "headers" not in out["mcpServers"]["b"]
    assert out["mcpServers"]["b"] == {"type": "http", "url": "https://b"}

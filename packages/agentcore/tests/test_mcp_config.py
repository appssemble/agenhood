from __future__ import annotations

import pytest

from agentcore.drivers.mcp_config import (
    CODEX_NOAUTH_PLACEHOLDER,
    codex_mcp_env,
    mcp_token_env_var,
    render_codex_mcp_toml,
    render_opencode_mcp,
)
from agentcore.models import ShimMcpServer

pytestmark = pytest.mark.unit


def test_token_env_var_uppercases_and_underscores() -> None:
    assert mcp_token_env_var("my-cool-server") == "MCP_MY_COOL_SERVER_TOKEN"


def test_opencode_bearer_inlines_authorization_header() -> None:
    out = render_opencode_mcp([ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t0k")])
    e = out["mcp"]["lin"]
    assert e == {"type": "remote", "url": "https://m", "enabled": True,
                 "headers": {"Authorization": "Bearer t0k"}}


def test_opencode_header_uses_custom_name() -> None:
    out = render_opencode_mcp([ShimMcpServer(name="fig", url="https://m",
                              auth_type="header", auth_header_name="X-Api-Key", secret="k")])
    assert out["mcp"]["fig"]["headers"] == {"X-Api-Key": "k"}


def test_opencode_none_has_no_headers() -> None:
    out = render_opencode_mcp([ShimMcpServer(name="pub", url="https://m")])
    assert "headers" not in out["mcp"]["pub"]


def test_codex_bearer_emits_env_var_ref() -> None:
    toml = render_codex_mcp_toml([ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t")])
    assert "[mcp_servers.lin]" in toml
    assert 'url = "https://m"' in toml
    assert "enabled = true" in toml
    assert 'bearer_token_env_var = "MCP_LIN_TOKEN"' in toml


def test_codex_header_emits_env_http_headers() -> None:
    toml = render_codex_mcp_toml([ShimMcpServer(name="fig", url="https://m",
                                 auth_type="header", auth_header_name="X-Api-Key", secret="k")])
    assert 'env_http_headers = { "X-Api-Key" = "MCP_FIG_TOKEN" }' in toml


def test_codex_real_secret_takes_precedence_over_placeholder() -> None:
    env = codex_mcp_env([
        ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t"),
        ShimMcpServer(name="pub", url="https://m"),
    ])
    # Real bearer secret is passed verbatim; the no-auth server still gets a
    # (distinct) placeholder so codex skips its OAuth auto-discovery.
    assert env["MCP_LIN_TOKEN"] == "t"
    assert env["MCP_PUB_TOKEN"] == CODEX_NOAUTH_PLACEHOLDER


def test_codex_noauth_emits_placeholder_bearer_to_skip_oauth_discovery() -> None:
    # In the egress-restricted sandbox codex's MCP OAuth auto-discovery can never
    # succeed and costs ~40s of startup; a static bearer token makes codex skip
    # it. No-auth servers must therefore still get a (placeholder) token ref.
    toml = render_codex_mcp_toml([ShimMcpServer(name="pub", url="https://m")])
    assert "[mcp_servers.pub]" in toml
    assert 'bearer_token_env_var = "MCP_PUB_TOKEN"' in toml


def test_codex_noauth_env_carries_nonempty_placeholder() -> None:
    env = codex_mcp_env([ShimMcpServer(name="pub", url="https://m")])
    # Must be non-empty: codex falls back to OAuth discovery for an empty token.
    assert env["MCP_PUB_TOKEN"] == CODEX_NOAUTH_PLACEHOLDER
    assert CODEX_NOAUTH_PLACEHOLDER

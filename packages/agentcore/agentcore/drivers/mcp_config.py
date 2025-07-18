"""Pure renderers that turn resolved ShimMcpServer specs into the two native
driver config formats. No I/O — the drivers do the file writing.

opencode: a JSON config block where the auth secret is inlined into ``headers``.
codex: a TOML ``[mcp_servers.<name>]`` block where the secret is NEVER inlined;
it is referenced by the name of an environment variable the codex driver sets on
the child process (codex has no inline-token field for HTTP transport).
"""
from __future__ import annotations

from typing import Any

from agentcore.models import ShimMcpServer


def mcp_token_env_var(name: str) -> str:
    """Deterministic env-var name carrying a server's secret for codex.
    The kebab-case server name is uppercased with '-' -> '_'."""
    return "MCP_" + name.upper().replace("-", "_") + "_TOKEN"


# Inert bearer value handed to codex for every HTTP MCP server that has no real
# static auth. Its only job is to make codex treat the server as authenticated
# and SKIP MCP OAuth auto-discovery: in the egress-restricted agent sandbox the
# rmcp discovery client bypasses the proxy, so those 8 well-known-endpoint probes
# can never succeed and just add ~40s of startup latency (~5s connect-timeout
# each). codex needs a non-empty token to skip discovery — an empty value makes
# it probe anyway. Most no-auth servers ignore the Authorization header.
CODEX_NOAUTH_PLACEHOLDER = "codex-noauth-skip-oauth-discovery"


def _opencode_headers(s: ShimMcpServer) -> dict[str, str] | None:
    if s.auth_type == "bearer" and s.secret:
        return {"Authorization": f"Bearer {s.secret}"}
    if s.auth_type == "header" and s.auth_header_name and s.secret:
        return {s.auth_header_name: s.secret}
    return None


def render_opencode_mcp(servers: list[ShimMcpServer]) -> dict[str, Any]:
    """Build opencode's ``{"mcp": {...}}`` config fragment (secrets inlined)."""
    mcp: dict[str, Any] = {}
    for s in servers:
        entry: dict[str, Any] = {"type": "remote", "url": s.url, "enabled": True}
        headers = _opencode_headers(s)
        if headers:
            entry["headers"] = headers
        mcp[s.name] = entry
    return {"mcp": mcp}


def _toml_basic_string(value: str) -> str:
    """Minimal TOML basic-string escaping (backslash + double-quote)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_codex_mcp_toml(servers: list[ShimMcpServer]) -> str:
    """Build codex's ``[mcp_servers.<name>]`` TOML blocks. Secrets are referenced
    by env-var name (see ``codex_mcp_env``), never inlined."""
    blocks: list[str] = []
    for s in servers:
        lines = [f"[mcp_servers.{s.name}]",
                 f"url = {_toml_basic_string(s.url)}",
                 "enabled = true"]
        var = mcp_token_env_var(s.name)
        if s.auth_type == "bearer" and s.secret:
            lines.append(f"bearer_token_env_var = {_toml_basic_string(var)}")
        elif s.auth_type == "header" and s.auth_header_name and s.secret:
            lines.append(
                f"env_http_headers = {{ {_toml_basic_string(s.auth_header_name)} = "
                f"{_toml_basic_string(var)} }}"
            )
        else:
            # No real static auth: emit a placeholder bearer token ref so codex
            # skips its (always-futile-here) OAuth auto-discovery — see
            # CODEX_NOAUTH_PLACEHOLDER. codex_mcp_env sets the var's value.
            lines.append(f"bearer_token_env_var = {_toml_basic_string(var)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def codex_mcp_env(servers: list[ShimMcpServer]) -> dict[str, str]:
    """Map each server to the child-process env var codex reads for its token.

    Servers with real static auth carry their secret verbatim; every other HTTP
    server carries CODEX_NOAUTH_PLACEHOLDER so codex skips MCP OAuth discovery
    (see render_codex_mcp_toml / CODEX_NOAUTH_PLACEHOLDER)."""
    env: dict[str, str] = {}
    for s in servers:
        if s.auth_type in ("bearer", "header") and s.secret:
            env[mcp_token_env_var(s.name)] = s.secret
        else:
            env[mcp_token_env_var(s.name)] = CODEX_NOAUTH_PLACEHOLDER
    return env


def render_claude_mcp_json(servers: list[ShimMcpServer]) -> dict[str, Any]:
    """Build Claude Code's hermetic ``{"mcpServers": {...}}`` config (remote HTTP
    only; secrets inlined into ``headers``, like opencode)."""
    mcp: dict[str, Any] = {}
    for s in servers:
        entry: dict[str, Any] = {"type": "http", "url": s.url}
        headers = _opencode_headers(s)
        if headers:
            entry["headers"] = headers
        mcp[s.name] = entry
    return {"mcpServers": mcp}

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.drivers.codex import codex_config_path, codex_home, write_codex_mcp
from agentcore.drivers.mcp_config import codex_mcp_env
from agentcore.models import ShimMcpServer

pytestmark = pytest.mark.unit


def test_config_path_under_codex_home(tmp_path):
    expected = Path(codex_home(str(tmp_path))) / "config.toml"
    assert codex_config_path(str(tmp_path)) == str(expected)


def test_write_creates_config_toml(tmp_path):
    n = write_codex_mcp(str(tmp_path), [
        ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t"),
    ])
    assert n == 1
    toml = Path(codex_config_path(str(tmp_path))).read_text()
    assert "[mcp_servers.lin]" in toml
    assert 'bearer_token_env_var = "MCP_LIN_TOKEN"' in toml


def test_write_empty_is_noop(tmp_path):
    assert write_codex_mcp(str(tmp_path), []) == 0
    assert not Path(codex_config_path(str(tmp_path))).exists()


def test_env_for_secret_server():
    env = codex_mcp_env([ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t")])
    assert env["MCP_LIN_TOKEN"] == "t"

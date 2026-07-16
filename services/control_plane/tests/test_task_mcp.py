from __future__ import annotations

import pytest

from agentcore.models import AgentConfig
from control_plane.auth.crypto import encrypt_secret
from control_plane.routers.tasks import build_task_mcp_servers

pytestmark = pytest.mark.unit

KEY = b"0" * 32


def _rows():
    return [
        {"id": "mcp_a", "name": "a", "url": "https://a", "auth_type": "bearer",
         "auth_header_name": None, "secret_ciphertext": encrypt_secret("ta", KEY), "enabled": True},
        {"id": "mcp_b", "name": "b", "url": "https://b", "auth_type": "none",
         "auth_header_name": None, "secret_ciphertext": None, "enabled": True},
    ]


def test_build_task_mcp_resolves_for_vanilla() -> None:
    # vanilla's DriverCapabilities.supports_mcp is True (Task 6): the
    # in-process driver resolves MCP servers too, not just the shell-out CLIs.
    cfg = AgentConfig(driver="vanilla", model="m", mcp_servers=["mcp_a"])
    out = build_task_mcp_servers(cfg, _rows(), KEY)
    assert [s.name for s in out] == ["a"]


def test_build_task_mcp_empty_for_unknown_driver() -> None:
    cfg = AgentConfig(driver="not-a-real-driver", model="m", mcp_servers=["mcp_a"])
    assert build_task_mcp_servers(cfg, _rows(), KEY) == []


def test_build_task_mcp_resolves_for_opencode() -> None:
    cfg = AgentConfig(driver="opencode", model="m", mcp_servers=["mcp_b", "mcp_a"])
    out = build_task_mcp_servers(cfg, _rows(), KEY)
    assert [s.name for s in out] == ["b", "a"]
    assert out[1].secret == "ta"


def test_build_task_mcp_empty_when_none_selected() -> None:
    cfg = AgentConfig(driver="codex", model="m", mcp_servers=[])
    assert build_task_mcp_servers(cfg, _rows(), KEY) == []

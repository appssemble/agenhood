from __future__ import annotations

import pytest

from control_plane.schemas import ConfigPatch

pytestmark = pytest.mark.unit


def test_config_patch_round_trips_mcp_servers() -> None:
    patch = ConfigPatch(driver="opencode", model="m", mcp_servers=["mcp_a", "mcp_b"])
    cfg = patch.to_agent_config()
    assert cfg.mcp_servers == ["mcp_a", "mcp_b"]


def test_config_patch_defaults_mcp_servers_empty() -> None:
    cfg = ConfigPatch(driver="opencode", model="m").to_agent_config()
    assert cfg.mcp_servers == []

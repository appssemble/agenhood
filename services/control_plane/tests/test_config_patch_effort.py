"""ConfigPatch.effort round-trips into AgentConfig; omission clears."""
from __future__ import annotations

from control_plane.schemas import ConfigPatch


def test_patch_effort_flows_into_agent_config():
    patch = ConfigPatch(driver="codex", model="gpt-5.4", effort="max")
    assert patch.to_agent_config().effort == "max"


def test_patch_without_effort_clears_it():
    patch = ConfigPatch(driver="codex", model="gpt-5.4")
    assert patch.to_agent_config().effort is None

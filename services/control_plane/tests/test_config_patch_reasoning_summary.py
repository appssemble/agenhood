"""ConfigPatch.reasoning_summary round-trips into AgentConfig; omission clears."""
from __future__ import annotations

from control_plane.schemas import ConfigPatch


def test_patch_reasoning_summary_flows_into_agent_config():
    patch = ConfigPatch(driver="codex", model="gpt-5.4", reasoning_summary=True)
    assert patch.to_agent_config().reasoning_summary is True


def test_patch_without_reasoning_summary_turns_it_off():
    patch = ConfigPatch(driver="codex", model="gpt-5.4")
    assert patch.to_agent_config().reasoning_summary is False

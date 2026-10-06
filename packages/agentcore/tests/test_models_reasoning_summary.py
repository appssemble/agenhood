"""AgentConfig/TaskBody `reasoning_summary`: optional, back-compat."""
from __future__ import annotations

from agentcore.models import AgentConfig, TaskBody


def test_agent_config_reasoning_summary_defaults_to_off():
    cfg = AgentConfig(driver="codex", model="gpt-5.6-sol")
    assert cfg.reasoning_summary is False


def test_old_config_snapshot_without_reasoning_summary_parses():
    cfg = AgentConfig(**{"driver": "codex", "model": "gpt-5.6-sol"})
    assert cfg.model_dump()["reasoning_summary"] is False


def test_task_body_reasoning_summary_is_an_optional_override():
    assert TaskBody(prompt="hi").reasoning_summary is None
    assert TaskBody(prompt="hi", reasoning_summary=True).reasoning_summary is True
    assert TaskBody(prompt="hi", reasoning_summary=False).reasoning_summary is False

"""AgentConfig/TaskBody `effort`: optional, value-checked, back-compat."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcore.models import AgentConfig, TaskBody


def test_agent_config_effort_defaults_to_none():
    cfg = AgentConfig(driver="codex", model="gpt-5.6-sol")
    assert cfg.effort is None


def test_old_config_snapshot_without_effort_parses():
    # Snapshots persisted before the field existed must keep deserializing.
    cfg = AgentConfig(**{"driver": "opencode", "model": "anthropic/claude-sonnet-5"})
    assert cfg.effort is None
    assert "effort" in cfg.model_dump()


def test_agent_config_rejects_unknown_effort():
    with pytest.raises(ValidationError):
        AgentConfig(driver="codex", model="gpt-5.6-sol", effort="ultra")


def test_task_body_effort_optional_and_checked():
    assert TaskBody(prompt="hi").effort is None
    assert TaskBody(prompt="hi", effort="high").effort == "high"
    with pytest.raises(ValidationError):
        TaskBody(prompt="hi", effort="minimal")

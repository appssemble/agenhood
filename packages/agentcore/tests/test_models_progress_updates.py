"""AgentConfig/TaskBody `progress_updates` and the `progress` event."""
from __future__ import annotations

from agentcore import events
from agentcore.models import AgentConfig, TaskBody


def test_agent_config_progress_updates_defaults_to_off():
    assert AgentConfig(driver="codex", model="gpt-5.6-sol").progress_updates is False


def test_task_body_progress_updates_is_an_optional_override():
    assert TaskBody(prompt="hi").progress_updates is None
    assert TaskBody(prompt="hi", progress_updates=True).progress_updates is True


def test_progress_is_an_event_type():
    assert "progress" in events.EVENT_TYPES


def test_progress_payload_carries_the_text():
    assert events.progress("Vou ler o ficheiro.") == {"text": "Vou ler o ficheiro."}

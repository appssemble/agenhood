"""progress_updates: codex-only container setting with a per-task override."""
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig, TaskBody
from control_plane.config_validation import PROGRESS_UPDATES_DRIVERS, validate_config
from control_plane.errors import APIError
from control_plane.routers.tasks import (
    PromptTaskBody,
    apply_progress_updates_override,
    build_task_row,
)
from control_plane.schemas import ConfigPatch

pytestmark = pytest.mark.unit

LIMITS = {"allowed_drivers": ["vanilla", "opencode", "claude-code", "codex"]}


def _cfg(driver: str = "codex", progress_updates: bool = False) -> AgentConfig:
    return AgentConfig(driver=driver, model="gpt-5.4", progress_updates=progress_updates)


def test_progress_updates_drivers_is_codex_only():
    assert PROGRESS_UPDATES_DRIVERS == {"codex"}


def test_progress_updates_accepted_for_codex():
    validate_config(AgentConfig(driver="codex", model="gpt-5.5", progress_updates=True), LIMITS)


def test_progress_updates_rejected_for_vanilla():
    cfg = AgentConfig(driver="vanilla", model="claude-opus-4-7", progress_updates=True)
    with pytest.raises(APIError) as exc:
        validate_config(cfg, LIMITS)
    assert exc.value.field == "progress_updates"


def test_override_turns_it_on_and_off():
    assert apply_progress_updates_override(_cfg(), True).progress_updates is True
    on = _cfg(progress_updates=True)
    assert apply_progress_updates_override(on, False).progress_updates is False


def test_no_override_keeps_container_default():
    cfg = _cfg(progress_updates=True)
    assert apply_progress_updates_override(cfg, None) is cfg


def test_turning_it_on_rejected_for_vanilla():
    with pytest.raises(APIError) as exc:
        apply_progress_updates_override(_cfg(driver="vanilla"), True)
    assert exc.value.field == "progress_updates"


def test_snapshot_carries_effective_progress_updates():
    config = apply_progress_updates_override(_cfg(), True)
    row = build_task_row(
        task_id="t1", tenant_id="tn1", container_id="c1",
        task=TaskBody(prompt="hi"), config=config,
        scheduled_task_id=None, session_id=None,
    )
    assert row["config_snapshot"]["progress_updates"] is True


def test_prompt_task_body_carries_progress_updates():
    assert PromptTaskBody(prompt_id="p1", progress_updates=True).progress_updates is True
    assert PromptTaskBody(prompt_id="p1").progress_updates is None


def test_config_patch_round_trips_progress_updates():
    on = ConfigPatch(driver="codex", model="gpt-5.4", progress_updates=True)
    assert on.to_agent_config().progress_updates is True
    off = ConfigPatch(driver="codex", model="gpt-5.4")
    assert off.to_agent_config().progress_updates is False

"""Per-task reasoning_summary override folds into the config snapshot."""
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig, TaskBody
from control_plane.errors import APIError
from control_plane.routers.tasks import (
    PromptTaskBody,
    apply_reasoning_summary_override,
    build_task_row,
)

pytestmark = pytest.mark.unit


def _cfg(driver: str = "codex", reasoning_summary: bool = False) -> AgentConfig:
    return AgentConfig(driver=driver, model="gpt-5.4", reasoning_summary=reasoning_summary)


def test_override_turns_it_on():
    assert apply_reasoning_summary_override(_cfg(), True).reasoning_summary is True


def test_override_turns_it_off():
    out = apply_reasoning_summary_override(_cfg(reasoning_summary=True), False)
    assert out.reasoning_summary is False


def test_no_override_keeps_container_default():
    cfg = _cfg(reasoning_summary=True)
    assert apply_reasoning_summary_override(cfg, None) is cfg


def test_turning_it_on_rejected_for_vanilla():
    with pytest.raises(APIError) as exc:
        apply_reasoning_summary_override(_cfg(driver="vanilla"), True)
    assert exc.value.field == "reasoning_summary"


def test_turning_it_off_allowed_for_vanilla():
    out = apply_reasoning_summary_override(_cfg(driver="vanilla"), False)
    assert out.reasoning_summary is False


def test_snapshot_carries_effective_reasoning_summary():
    config = apply_reasoning_summary_override(_cfg(), True)
    row = build_task_row(
        task_id="t1", tenant_id="tn1", container_id="c1",
        task=TaskBody(prompt="hi"), config=config,
        scheduled_task_id=None, session_id=None,
    )
    assert row["config_snapshot"]["reasoning_summary"] is True


def test_prompt_task_body_carries_reasoning_summary():
    assert PromptTaskBody(prompt_id="p1", reasoning_summary=True).reasoning_summary is True
    assert PromptTaskBody(prompt_id="p1").reasoning_summary is None

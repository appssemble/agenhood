"""Per-task effort override folds into the config snapshot (pure helper)."""
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig
from control_plane.errors import APIError
from control_plane.routers.tasks import apply_effort_override, build_task_row


def _cfg(driver: str = "codex", effort: str | None = None) -> AgentConfig:
    return AgentConfig(driver=driver, model="gpt-5.4", effort=effort)


def test_override_replaces_container_default():
    out = apply_effort_override(_cfg(effort="medium"), "low")
    assert out.effort == "low"


def test_no_override_keeps_container_default():
    cfg = _cfg(effort="high")
    assert apply_effort_override(cfg, None) is cfg


def test_override_rejected_for_vanilla():
    with pytest.raises(APIError) as exc:
        apply_effort_override(_cfg(driver="vanilla"), "low")
    assert exc.value.field == "effort"


def test_snapshot_carries_effective_effort():
    from agentcore.models import TaskBody

    config = apply_effort_override(_cfg(effort=None), "max")
    row = build_task_row(
        task_id="t1", tenant_id="tn1", container_id="c1",
        task=TaskBody(prompt="hi"), config=config,
        scheduled_task_id=None, session_id=None,
    )
    assert row["config_snapshot"]["effort"] == "max"

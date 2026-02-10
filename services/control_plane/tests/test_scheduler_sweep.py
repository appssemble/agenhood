"""scheduler unit tests: pure advance values + submit-and-record outcomes."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

import control_plane.scheduler as scheduler_mod
from control_plane.scheduler import _advance_values

pytestmark = pytest.mark.unit


class _DueRow:
    def __init__(self, schedule):
        self.id = "sch_1"
        self.tenant_id = "ten_1"
        self.schedule = schedule
        self.timezone = "UTC"
        self.target = {
            "kind": "prompt",
            "prompt_id": "pmt_1",
            "container_id": "con_1",
            "variables": {},
        }


def test_advance_recurring_moves_to_next_slot():
    vals = _advance_values(
        {"kind": "recurring", "unit": "day", "time": "09:00"}, "UTC",
        datetime(2026, 6, 17, 10, 0, tzinfo=UTC),
    )
    assert vals["next_run_at"] == datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    assert "enabled" not in vals


def test_advance_once_disables():
    vals = _advance_values({"kind": "once"}, "UTC", datetime(2026, 6, 17, 10, 0, tzinfo=UTC))
    assert vals["next_run_at"] is None
    assert vals["enabled"] is False


@pytest.mark.asyncio
async def test_submit_due_schedule_records_submitted(monkeypatch):
    async def fake_load_prompt_row(session, tenant_id, prompt_id):
        return {"body": "go", "variables": []}

    monkeypatch.setattr(scheduler_mod, "_load_prompt_row", fake_load_prompt_row)

    async def fake_core(session, **kwargs):
        assert kwargs["cid"] == "con_1"
        assert kwargs["body"].metadata.get("scheduled_task_id") == "sch_1"
        return {"task_id": "tsk_1", "status": "running"}

    monkeypatch.setattr(scheduler_mod, "submit_task_core", fake_core)
    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await scheduler_mod._submit_due_schedule(
        session=object(), row=_DueRow({"kind": "recurring", "unit": "day", "time": "09:00"}),
        now=datetime(2026, 6, 17, 10, 0, tzinfo=UTC),
        settings=object(), session_factory=lambda: None,
        docker_client=object(), shim_dispatcher=object(),
    )
    assert recorded["last_status"] == "submitted"
    assert recorded["last_run_ref"] == "tsk_1"


@pytest.mark.asyncio
async def test_submit_due_schedule_records_failed(monkeypatch):
    async def fake_load_prompt_row(session, tenant_id, prompt_id):
        return {"body": "go", "variables": []}

    monkeypatch.setattr(scheduler_mod, "_load_prompt_row", fake_load_prompt_row)

    async def boom(session, **kwargs):
        raise RuntimeError("shim down")

    monkeypatch.setattr(scheduler_mod, "submit_task_core", boom)
    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await scheduler_mod._submit_due_schedule(
        session=object(), row=_DueRow({"kind": "once"}),
        now=datetime(2026, 6, 17, 10, 0, tzinfo=UTC),
        settings=object(), session_factory=lambda: None,
        docker_client=object(), shim_dispatcher=object(),
    )
    assert recorded["last_status"] == "failed"
    assert recorded["last_run_ref"] is None

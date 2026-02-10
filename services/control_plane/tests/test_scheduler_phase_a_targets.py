"""Unit tests: Phase A fire path branches on target kind (Task 19).

Covers:
- prompt target → calls submit_task_core with the resolved prompt, records last_run_ref
- workflow target with an ACTIVE run → records last_status='skipped_overlap', does NOT call start_run
- workflow target with NO active run → calls start_run once, records last_run_ref
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

import control_plane.scheduler as scheduler_mod

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)


class _DueRow:
    def __init__(self, target: dict):
        self.id = "sch_1"
        self.tenant_id = "ten_1"
        self.schedule = {"kind": "recurring", "unit": "day", "time": "09:00"}
        self.timezone = "UTC"
        self.target = target


async def _fire(row, monkeypatch_apply_fn):
    """Helper: call _submit_due_schedule with sensible no-op defaults."""
    await scheduler_mod._submit_due_schedule(
        session=object(),
        row=row,
        now=_NOW,
        settings=object(),
        session_factory=lambda: None,
        docker_client=object(),
        shim_dispatcher=object(),
    )


# ---------------------------------------------------------------------------
# prompt target
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompt_target_calls_submit_task_core_with_resolved_prompt(monkeypatch):
    """Prompt target resolves body+variables and passes TaskBody to submit_task_core."""
    row = _DueRow({
        "kind": "prompt",
        "prompt_id": "pmt_1",
        "container_id": "con_1",
        "variables": {"name": "world"},
    })

    async def fake_load_prompt_row(session, tenant_id, prompt_id):
        assert tenant_id == "ten_1"
        assert prompt_id == "pmt_1"
        return {"body": "Hello {{name}}", "variables": [{"name": "name", "default": ""}]}

    monkeypatch.setattr(scheduler_mod, "_load_prompt_row", fake_load_prompt_row)

    submitted = []

    async def fake_core(session, **kwargs):
        submitted.append(kwargs)
        return {"task_id": "tsk_1"}

    monkeypatch.setattr(scheduler_mod, "submit_task_core", fake_core)

    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await _fire(row, fake_apply)

    assert len(submitted) == 1
    assert submitted[0]["cid"] == "con_1"
    assert submitted[0]["tenant_id"] == "ten_1"
    assert submitted[0]["body"].prompt == "Hello world"
    assert submitted[0]["body"].metadata.get("scheduled_task_id") == "sch_1"
    assert recorded["last_run_ref"] == "tsk_1"
    assert recorded["last_status"] == "submitted"


@pytest.mark.asyncio
async def test_prompt_target_records_failed_on_submit_error(monkeypatch):
    """If submit_task_core raises, last_status='failed' and last_run_ref is None."""
    row = _DueRow({
        "kind": "prompt",
        "prompt_id": "pmt_1",
        "container_id": "con_1",
    })

    async def fake_load_prompt_row(session, tenant_id, prompt_id):
        return {"body": "Hello", "variables": []}

    monkeypatch.setattr(scheduler_mod, "_load_prompt_row", fake_load_prompt_row)

    async def boom(session, **kwargs):
        raise RuntimeError("shim down")

    monkeypatch.setattr(scheduler_mod, "submit_task_core", boom)

    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await _fire(row, fake_apply)

    assert recorded["last_status"] == "failed"
    assert recorded["last_run_ref"] is None


# ---------------------------------------------------------------------------
# workflow target — overlap guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_target_with_active_run_skips(monkeypatch):
    """If a run for this scheduled_task_id is already running, skip and record skipped_overlap."""
    row = _DueRow({"kind": "workflow", "workflow_id": "wf_1"})

    async def fake_overlap(session, scheduled_task_id):
        assert scheduled_task_id == "sch_1"
        return True  # overlap exists

    monkeypatch.setattr(scheduler_mod, "_workflow_overlap_exists", fake_overlap)

    start_called = []

    async def fake_start_run(session, **kwargs):
        start_called.append(kwargs)
        return "wfr_new"

    monkeypatch.setattr(scheduler_mod, "start_run", fake_start_run)

    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await _fire(row, fake_apply)

    assert start_called == []  # start_run must NOT be called
    assert recorded["last_status"] == "skipped_overlap"
    assert recorded.get("last_run_ref") is None


@pytest.mark.asyncio
async def test_workflow_target_with_no_active_run_starts(monkeypatch):
    """If no active run exists, start_run is called once and last_run_ref is set."""
    row = _DueRow({"kind": "workflow", "workflow_id": "wf_1"})

    async def fake_overlap(session, scheduled_task_id):
        return False  # no active run

    monkeypatch.setattr(scheduler_mod, "_workflow_overlap_exists", fake_overlap)

    async def fake_load_workflow_row(session, tenant_id, workflow_id):
        assert tenant_id == "ten_1"
        assert workflow_id == "wf_1"
        return {"id": "wf_1", "steps": [{"prompt_id": "pmt_a", "container_id": "con_1"}]}

    monkeypatch.setattr(scheduler_mod, "_load_workflow_row", fake_load_workflow_row)

    start_called = []

    async def fake_start_run(session, **kwargs):
        start_called.append(kwargs)
        return "wfr_1"

    monkeypatch.setattr(scheduler_mod, "start_run", fake_start_run)

    recorded = {}

    async def fake_apply(session, sid, values):
        recorded.update(values)

    monkeypatch.setattr(scheduler_mod, "_apply_schedule_update", fake_apply)

    await _fire(row, fake_apply)

    assert len(start_called) == 1
    assert start_called[0]["trigger_source"] == "schedule"
    assert start_called[0]["scheduled_task_id"] == "sch_1"
    assert start_called[0]["tenant_id"] == "ten_1"
    assert start_called[0]["workflow"] == {
        "id": "wf_1",
        "steps": [{"prompt_id": "pmt_a", "container_id": "con_1"}],
    }
    assert recorded["last_run_ref"] == "wfr_1"
    assert recorded["last_status"] == "submitted"

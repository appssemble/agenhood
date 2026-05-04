from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import control_plane.workflow_engine as eng

pytestmark = pytest.mark.unit


class _RecDB:
    """Records execute() statements and commits; returns empty results."""

    def __init__(self) -> None:
        self.executes: list[Any] = []
        self.commits = 0

    async def execute(self, stmt: Any, *a: Any, **k: Any) -> None:
        self.executes.append(stmt)
        return None

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_apply_run_update_without_event_executes_only_update():
    db = _RecDB()
    await eng._apply_run_update(db, "wfr_1", {"status": "running"}, commit=False)
    assert len(db.executes) == 1          # update only
    assert db.commits == 0


@pytest.mark.asyncio
async def test_apply_run_update_with_event_emits_in_same_txn():
    db = _RecDB()
    await eng._apply_run_update(
        db, "wfr_1", {"status": "completed"},
        commit=True, event=("completed", {"step_count": 2}),
    )
    assert len(db.executes) == 2          # update + event insert
    assert db.commits == 1                # single commit covers both


def _const(value):
    async def _fn(*a, **k):
        return value
    return _fn


def _aiter(lst):
    async def _fn(*a, **k):
        return lst
    return _fn


class _Run:
    def __init__(self, **kw):
        self.id = kw.get("id", "wfr_1")
        self.workflow_id = "wf_1"
        self.tenant_id = "ten_1"
        self.status = "running"
        self.cursor = kw.get("cursor", 0)
        self.current_task_id = kw.get("current_task_id", "tsk_0")
        self.step_count = kw.get("step_count", 2)
        self.step_started_at = kw.get("step_started_at", datetime.now(UTC))
        self.steps = kw.get("steps", None)


_STEPS = [
    {"prompt_id": "prm_a", "container_id": "con_1", "variables": {}},
    {"prompt_id": "prm_b", "container_id": "con_2", "variables": {}},
]


def _wire_events(monkeypatch, *, runs, status, steps=None, submit=None, timeout=None):
    """Capture (rid, values, event) passed to _apply_run_update."""
    applied = []

    monkeypatch.setattr(eng, "_claim_active_runs", _aiter(runs))
    monkeypatch.setattr(eng, "_task_status", _const((status, timeout)))
    monkeypatch.setattr(eng, "_load_workflow_steps",
                        _const(_STEPS if steps is None else steps))

    async def _apply(db, rid, values, *, commit=True, event=None):
        applied.append((rid, dict(values), event))

    monkeypatch.setattr(eng, "_apply_run_update", _apply)

    if submit is None:
        async def submit(session, **kw):
            return "tsk_next"
    monkeypatch.setattr(eng, "submit_step", submit)
    return applied


class _NullDB:
    async def execute(self, *a, **k):
        return None

    async def commit(self):
        return None


async def _advance(db):
    await eng.advance_workflow_runs(
        db, object(), object(), settings=object(), session_factory=lambda: None
    )


@pytest.mark.asyncio
async def test_complete_emits_completed_event(monkeypatch):
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=2)
    applied = _wire_events(monkeypatch, runs=[run], status="completed")
    await _advance(_NullDB())
    events = [e for _, _, e in applied if e is not None]
    assert ("completed", {"step_count": 2}) in events


@pytest.mark.asyncio
async def test_failed_step_emits_failed_event(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=3)
    applied = _wire_events(monkeypatch, runs=[run], status="failed")
    await _advance(_NullDB())
    evts = [e for _, _, e in applied if e is not None]
    assert any(t == "failed" and p.get("error_step") == 0 for t, p in evts)


@pytest.mark.asyncio
async def test_advance_emits_step_advanced_event(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2)

    async def submit(session, **kw):
        return "tsk_1"

    applied = _wire_events(monkeypatch, runs=[run], status="completed", submit=submit)
    await _advance(_NullDB())
    evts = [e for _, _, e in applied if e is not None]
    assert any(
        t == "step_advanced" and p == {"from_step": 0, "to_step": 1, "task_id": "tsk_1"}
        for t, p in evts
    )


@pytest.mark.asyncio
async def test_start_run_emits_started_event(monkeypatch):
    emitted = []

    async def fake_emit(db, run_id, type_, payload):
        emitted.append((type_, payload))

    async def fake_submit(session, **kw):
        return "tsk_0"

    monkeypatch.setattr(eng, "_emit_workflow_event", fake_emit)
    monkeypatch.setattr(eng, "submit_step", fake_submit)

    class _SessDB(_NullDB):
        pass

    workflow = {"id": "wf_1", "steps": _STEPS}
    await eng.start_run(
        _SessDB(), settings=object(), session_factory=lambda: None,
        docker_client=object(), shim_dispatcher=object(),
        tenant_id="ten_1", workflow=workflow, trigger_source="manual",
    )
    assert ("started", {
        "workflow_id": "wf_1", "step_count": 2,
        "trigger_source": "manual", "task_id": "tsk_0", "step": 0,
    }) in emitted

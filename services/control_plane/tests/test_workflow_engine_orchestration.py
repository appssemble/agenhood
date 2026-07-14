"""Unit tests for the workflow run-engine DB orchestration (Task 6).

These exercise advance_workflow_runs / start_run by monkeypatching the small
module-level DB-apply helpers (so we never reproduce SQLAlchemy result objects)
and a fake `db` whose .commit() is recorded in a shared ordered event log. The
event log lets us prove the critical invariant: the lock-releasing commit happens
BEFORE any submit I/O (claim -> commit -> submit).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import control_plane.workflow_engine as eng

pytestmark = pytest.mark.unit


# --- tiny async test helpers -------------------------------------------------
def _const(value: Any):
    async def _fn(*a: Any, **k: Any) -> Any:
        return value
    return _fn


def _aiter(lst: list[Any]):
    async def _fn(*a: Any, **k: Any) -> list[Any]:
        return lst
    return _fn


class _Run:
    def __init__(self, **kw: Any) -> None:
        self.id = kw.get("id", "wfr_1")
        self.workflow_id = "wf_1"
        self.tenant_id = "ten_1"
        self.status = "running"
        self.cursor = kw.get("cursor", 0)
        self.current_task_id = kw.get("current_task_id", "tsk_0")
        self.step_count = kw.get("step_count", 2)
        self.step_started_at = kw.get("step_started_at", datetime.now(UTC))
        self.steps = kw.get("steps", None)


class _FakeDB:
    """Records claim-phase UPDATE executes and commits into a shared event log."""

    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.commits = 0

    async def execute(self, stmt: Any, *a: Any, **k: Any) -> None:
        self.events.append(("execute", stmt))
        return None

    async def commit(self) -> None:
        self.commits += 1
        self.events.append(("commit", None))


_STEPS = [
    {"prompt_id": "prm_a", "container_id": "con_1", "variables": {}},
    {"prompt_id": "prm_b", "container_id": "con_2", "variables": {}},
]


def _wire(monkeypatch, *, runs, status, steps=None, submit=None, timeout=None):
    """Common monkeypatch wiring. Returns (events, applied, submitted).

    ``_task_status`` returns a (status, resolved_timeout_seconds) tuple; the
    ``timeout`` kwarg seeds the resolved timeout used by the step-timeout guard."""
    events: list[Any] = []
    applied: list[tuple[str, dict, bool]] = []
    submitted: list[tuple[int, str]] = []

    monkeypatch.setattr(eng, "_claim_active_runs", _aiter(runs))
    monkeypatch.setattr(eng, "_task_status", _const((status, timeout)))
    monkeypatch.setattr(eng, "_load_workflow_steps", _const(_STEPS if steps is None else steps))

    async def _apply(db, rid, values, *, commit=True, event=None):
        applied.append((rid, dict(values), commit))
        if event is not None:
            events.append(("event", rid, event[0]))
        if commit:
            events.append(("apply_commit", rid))

    monkeypatch.setattr(eng, "_apply_run_update", _apply)

    if submit is None:
        async def submit(session, **kw):
            events.append(("submit", kw["step_index"]))
            submitted.append((kw["step_index"], kw["step"]["container_id"]))
            return "tsk_1"
    monkeypatch.setattr(eng, "submit_step", submit)

    return events, applied, submitted


async def _run(db):
    await eng.advance_workflow_runs(
        db, object(), object(), settings=object(), session_factory=lambda: None
    )


@pytest.mark.asyncio
async def test_completed_step_advances_and_submits_next(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2)
    events, applied, submitted = _wire(monkeypatch, runs=[run], status="completed")
    db = _FakeDB(events)

    await _run(db)

    # advanced cursor to 1 under the lock (commit=False) ...
    assert any(v.get("cursor") == 1 and not commit for _, v, commit in applied)
    # ... submitted step 1 to ITS container ...
    assert submitted == [(1, "con_2")]
    # ... then persisted current_task_id (committed).
    assert any(v.get("current_task_id") == "tsk_1" and commit for _, v, commit in applied)
    # invariant: lock released (db.commit) BEFORE the submit I/O.
    assert db.commits == 1
    commit_idx = next(i for i, e in enumerate(events) if e[0] == "commit")
    submit_idx = next(i for i, e in enumerate(events) if e[0] == "submit")
    assert commit_idx < submit_idx


@pytest.mark.asyncio
async def test_failed_step_fails_run_and_does_not_submit(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=3)
    called = {"submit": False}

    async def submit(session, **kw):
        called["submit"] = True
        return "tsk_x"

    _, applied, _ = _wire(monkeypatch, runs=[run], status="failed", submit=submit)
    db = _FakeDB([])

    await _run(db)

    assert called["submit"] is False
    assert any(v.get("status") == "failed" and v.get("error_step") == 0 for _, v, _ in applied)


@pytest.mark.asyncio
async def test_completed_final_step_completes_run(monkeypatch):
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=2)
    _, applied, submitted = _wire(monkeypatch, runs=[run], status="completed")
    db = _FakeDB([])

    await _run(db)

    assert submitted == []
    assert any(v.get("status") == "completed" and v.get("current_task_id") is None
               for _, v, _ in applied)


@pytest.mark.asyncio
async def test_submit_failure_marks_run_failed(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2)

    async def boom(session, **kw):
        raise RuntimeError("shim down")

    _, applied, _ = _wire(monkeypatch, runs=[run], status="completed", submit=boom)
    db = _FakeDB([])

    await _run(db)

    # cursor advanced under lock, then submit raised -> run failed at next_cursor.
    assert any(v.get("status") == "failed" and v.get("error_step") == 1
               and "shim down" in (v.get("error_message") or "") for _, v, _ in applied)


@pytest.mark.asyncio
async def test_steps_trimmed_below_cursor_completes_cleanly(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2)
    # workflow now has only one step, so next_cursor (1) is out of range.
    _, applied, submitted = _wire(
        monkeypatch, runs=[run], status="completed", steps=[_STEPS[0]]
    )
    db = _FakeDB([])

    await _run(db)

    assert submitted == []
    assert any(v.get("status") == "completed" and v.get("current_task_id") is None
               for _, v, _ in applied)


@pytest.mark.asyncio
async def test_stuck_null_task_past_grace_fails_run(monkeypatch):
    run = _Run(
        cursor=0,
        current_task_id=None,
        step_count=2,
        step_started_at=datetime.now(UTC) - timedelta(seconds=eng.STEP_NULL_GRACE_SECONDS + 60),
    )
    _, applied, submitted = _wire(monkeypatch, runs=[run], status=None)
    db = _FakeDB([])

    await _run(db)

    assert submitted == []
    assert any(v.get("status") == "failed" and v.get("error_step") == 0 for _, v, _ in applied)


@pytest.mark.asyncio
async def test_step_running_past_timeout_fails_run(monkeypatch):
    # Non-terminal task whose step has been in flight past timeout + grace.
    old = datetime.now(UTC) - timedelta(
        seconds=300 + eng.STEP_TIMEOUT_GRACE_SECONDS + 30
    )
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=3, step_started_at=old)
    _, applied, submitted = _wire(
        monkeypatch, runs=[run], status="running", timeout=300
    )
    db = _FakeDB([])

    await _run(db)

    assert submitted == []
    assert any(
        v.get("status") == "failed"
        and v.get("error_step") == 1
        and v.get("error_message") == "step timed out / stuck"
        for _, v, _ in applied
    )


@pytest.mark.asyncio
async def test_step_running_within_timeout_waits(monkeypatch):
    # Fresh step_started_at: still within timeout -> wait (no fail, no submit).
    run = _Run(
        cursor=0, current_task_id="tsk_0", step_count=3,
        step_started_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    _, applied, submitted = _wire(
        monkeypatch, runs=[run], status="running", timeout=300
    )
    db = _FakeDB([])

    await _run(db)

    assert submitted == []
    assert applied == []  # no terminal bookkeeping at all


@pytest.mark.asyncio
async def test_start_run_atomic_no_row_on_submit_failure(monkeypatch):
    """If step-0 submit raises, start_run raises and NO workflow_runs row is
    inserted (no session.execute / no commit)."""
    calls: list[str] = []

    async def boom(session, **kw):
        raise RuntimeError("shim down")

    monkeypatch.setattr(eng, "submit_step", boom)

    class _Session:
        async def execute(self, *a: Any, **k: Any) -> None:
            calls.append("execute")

        async def commit(self) -> None:
            calls.append("commit")

    with pytest.raises(RuntimeError, match="shim down"):
        await eng.start_run(
            _Session(),
            settings=object(),
            session_factory=lambda: None,
            docker_client=object(),
            shim_dispatcher=object(),
            tenant_id="ten_1",
            workflow={"id": "wf_1", "steps": _STEPS},
            trigger_source="manual",
        )

    assert calls == []  # no insert, no commit -> no run row written


@pytest.mark.asyncio
async def test_no_active_runs_is_noop(monkeypatch):
    _, applied, submitted = _wire(monkeypatch, runs=[], status="completed")
    db = _FakeDB([])

    await _run(db)

    assert applied == []
    assert submitted == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_start_run_initializes_timeline(monkeypatch):
    captured: dict[str, Any] = {}

    class _RecSession:
        async def execute(self, stmt, *a, **k):
            # Only capture the first execute (workflow_runs insert); subsequent
            # executes (e.g. _emit_workflow_event) must not overwrite the params.
            if "params" not in captured:
                captured["params"] = stmt.compile().params
            return None
        async def commit(self):
            captured["committed"] = True

    async def fake_submit_step(session, **kw):
        return "tsk_0"

    monkeypatch.setattr(eng, "submit_step", fake_submit_step)

    wf = {
        "id": "wf_1",
        "steps": [
            {"prompt_id": "prm_a", "container_id": "con_1", "variables": {}},
            {"prompt_id": "prm_b", "container_id": "con_2", "variables": {}},
        ],
    }
    rid = await eng.start_run(
        _RecSession(),
        settings=object(), session_factory=lambda: None,
        docker_client=None, shim_dispatcher=None,
        tenant_id="ten_1", workflow=wf, trigger_source="manual",
    )
    assert rid.startswith("wfr_")
    steps = captured["params"]["steps"]
    assert [s["status"] for s in steps] == ["running", "pending"]
    assert steps[0]["task_id"] == "tsk_0"
    assert steps[0]["started_at"] is not None
    assert steps[0]["container_id"] == "con_1"


def _timeline(*statuses):
    return [
        {"step_index": i, "task_id": None, "container_id": f"con_{i+1}",
         "status": s, "started_at": None, "ended_at": None}
        for i, s in enumerate(statuses)
    ]


def _steps_of(applied, rid="wfr_1"):
    """Last staged `steps` value for a run id across all _apply calls."""
    vals = [v["steps"] for (r, v, _c) in applied if r == rid and "steps" in v]
    return vals[-1] if vals else None


@pytest.mark.asyncio
async def test_advance_marks_prev_completed_and_next_running_with_task(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2,
               steps=_timeline("running", "pending"))
    events, applied, submitted = _wire(monkeypatch, runs=[run], status="completed")
    db = _FakeDB(events)

    await _run(db)

    final = _steps_of(applied)
    assert final[0]["status"] == "completed" and final[0]["ended_at"] is not None
    assert final[1]["status"] == "running"
    assert final[1]["task_id"] == "tsk_1"
    assert final[1]["container_id"] == "con_2"  # live submit container
    # invariant preserved: lock released before submit
    commit_idx = next(i for i, e in enumerate(events) if e[0] == "commit")
    submit_idx = next(i for i, e in enumerate(events) if e[0] == "submit")
    assert commit_idx < submit_idx


@pytest.mark.asyncio
async def test_complete_marks_last_step_completed(monkeypatch):
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=2,
               steps=_timeline("completed", "running"))
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status="completed")
    await _run(_FakeDB([]))

    final = _steps_of(applied)
    assert final[1]["status"] == "completed" and final[1]["ended_at"] is not None


@pytest.mark.asyncio
async def test_failed_task_marks_step_failed(monkeypatch):
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=2,
               steps=_timeline("completed", "running"))
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status="failed")
    await _run(_FakeDB([]))

    final = _steps_of(applied)
    assert final[1]["status"] == "failed" and final[1]["ended_at"] is not None


@pytest.mark.asyncio
async def test_legacy_run_without_timeline_is_untouched(monkeypatch):
    run = _Run(cursor=1, current_task_id="tsk_1", step_count=2, steps=None)
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status="completed")
    await _run(_FakeDB([]))

    # status still advances, but no `steps` is ever staged for a legacy run
    assert any("status" in v for (_r, v, _c) in applied)
    assert _steps_of(applied) is None


@pytest.mark.asyncio
async def test_stuck_task_marks_step_failed_in_timeline(monkeypatch):
    # current_task_id=None + step_started_at old enough → is_stuck() → fail branch
    run = _Run(
        cursor=0,
        current_task_id=None,
        step_count=2,
        step_started_at=datetime.now(UTC) - timedelta(seconds=eng.STEP_NULL_GRACE_SECONDS + 60),
        steps=_timeline("running", "pending"),
    )
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status=None)
    await _run(_FakeDB([]))

    final = _steps_of(applied)
    assert final is not None
    assert final[run.cursor]["status"] == "failed"
    assert final[run.cursor]["ended_at"] is not None


@pytest.mark.asyncio
async def test_timed_out_step_marks_step_failed_in_timeline(monkeypatch):
    # Non-terminal in-flight task whose step_started_at exceeds timeout + grace
    old = datetime.now(UTC) - timedelta(
        seconds=300 + eng.STEP_TIMEOUT_GRACE_SECONDS + 30
    )
    run = _Run(
        cursor=1,
        current_task_id="tsk_1",
        step_count=3,
        step_started_at=old,
        steps=_timeline("completed", "running", "pending"),
    )
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status="running", timeout=300)
    await _run(_FakeDB([]))

    final = _steps_of(applied)
    assert final is not None
    assert final[run.cursor]["status"] == "failed"
    assert final[run.cursor]["ended_at"] is not None


@pytest.mark.asyncio
async def test_submit_failure_marks_next_step_failed_in_timeline(monkeypatch):
    # Advance run whose submit raises → next step's timeline entry must be failed
    async def boom(session, **kw):
        raise RuntimeError("nope")

    run = _Run(
        cursor=0,
        current_task_id="tsk_0",
        step_count=2,
        steps=_timeline("running", "pending"),
    )
    _events, applied, _sub = _wire(monkeypatch, runs=[run], status="completed", submit=boom)
    await _run(_FakeDB([]))

    final = _steps_of(applied)
    assert final is not None
    assert final[1]["status"] == "failed"
    assert final[1]["ended_at"] is not None


# ---- step export transfer (workflow file transfer) ---------------------------

_STEPS_EXPORTS = [
    {"prompt_id": "prm_a", "container_id": "con_1", "variables": {},
     "exports": ["out/**"]},
    {"prompt_id": "prm_b", "container_id": "con_2", "variables": {}},
]


def _wire_transfer(monkeypatch, result=None, exc=None):
    calls: list[dict] = []

    async def fake_transfer(session, **kw):
        calls.append(kw)
        if exc is not None:
            raise exc
        return result or {"files": 2, "bytes": 10}

    monkeypatch.setattr(eng, "transfer_step_exports", fake_transfer)
    return calls


@pytest.mark.asyncio
async def test_advance_transfers_exports_before_submit(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2,
               steps=_timeline("running", "pending"))
    events, applied, submitted = _wire(
        monkeypatch, runs=[run], status="completed", steps=_STEPS_EXPORTS,
    )
    calls = _wire_transfer(monkeypatch)
    db = _FakeDB(events)

    await _run(db)

    assert len(calls) == 1
    assert calls[0]["exports"] == ["out/**"]
    assert calls[0]["source_cid"] == "con_1"
    assert calls[0]["dest_cid"] == "con_2"
    assert submitted == [(1, "con_2")]
    # files_transferred event emitted and timeline carries the summary
    assert ("event", "wfr_1", "files_transferred") in events
    final = _steps_of(applied)
    assert final[0]["transfer"] == {"files": 2, "bytes": 10}


@pytest.mark.asyncio
async def test_advance_without_exports_never_calls_transfer(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2,
               steps=_timeline("running", "pending"))
    _, _applied, submitted = _wire(monkeypatch, runs=[run], status="completed")
    calls = _wire_transfer(monkeypatch)

    await _run(_FakeDB([]))

    assert calls == []
    assert submitted == [(1, "con_2")]


@pytest.mark.asyncio
async def test_transfer_failure_fails_run_at_exporting_step(monkeypatch):
    from control_plane.workflow_transfer import WorkflowTransferError

    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2,
               steps=_timeline("running", "pending"))
    _, applied, submitted = _wire(
        monkeypatch, runs=[run], status="completed", steps=_STEPS_EXPORTS,
    )
    _wire_transfer(
        monkeypatch,
        exc=WorkflowTransferError("export pattern 'out/**' matched no files"),
    )

    await _run(_FakeDB([]))

    assert submitted == []  # next step never submitted
    assert any(
        v.get("status") == "failed" and v.get("error_step") == 0
        and "out/**" in (v.get("error_message") or "")
        for _, v, _ in applied
    )
    final = _steps_of(applied)
    assert final[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_transfer_success_on_legacy_run_without_timeline(monkeypatch):
    run = _Run(cursor=0, current_task_id="tsk_0", step_count=2, steps=None)
    events, _applied, submitted = _wire(
        monkeypatch, runs=[run], status="completed", steps=_STEPS_EXPORTS,
    )
    _wire_transfer(monkeypatch)
    db = _FakeDB(events)

    await _run(db)

    assert submitted == [(1, "con_2")]  # legacy runs still transfer + submit

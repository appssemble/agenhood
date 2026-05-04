"""Sequential multi-container workflow run engine.

Phase B of the scheduler sweep advances active workflow_runs. Decision logic is
isolated in pure helpers (terminal_action / is_stuck); the DB orchestration
(advance_workflow_runs, start_run) follows the scheduler's claim -> commit ->
submit discipline and never holds a row lock across the shim network call.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agentcore.models import TaskBody
from control_plane.ids import new_workflow_run_id
from control_plane.models_db import (
    prompts,
    tasks,
    workflow_events,
    workflow_runs,
    workflows,
)
from control_plane.prompts_service import resolve_body
from control_plane.routers.tasks import submit_task_core
from control_plane.workflow_timeline import (
    init_timeline,
    mark_completed,
    mark_failed,
    mark_running,
    mark_task,
)

STEP_NULL_GRACE_SECONDS = 120

# A run whose current step's task is stuck non-terminal (pending/running) past its
# resolved timeout + this grace must be failed, so a run never hangs forever (spec
# Run-engine §). The default is the platform's default task-timeout ceiling
# (tenant_defaults.default_task_timeout_seconds == 1800); it is only used as a last
# resort when neither the task body nor its config snapshot carries a timeout.
STEP_DEFAULT_TIMEOUT_SECONDS = 1800
STEP_TIMEOUT_GRACE_SECONDS = 120

_TERMINAL_FAIL = {"failed", "cancelled", "timed_out"}


def terminal_action(cursor: int, step_count: int, task_status: str) -> str:
    """What to do with a run whose current step's task is in `task_status`."""
    if task_status == "completed":
        return "advance" if cursor + 1 < step_count else "complete"
    if task_status in _TERMINAL_FAIL:
        return "fail"
    return "wait"  # pending / running / unknown


def is_stuck(
    current_task_id: str | None,
    step_started_at: datetime | None,
    now: datetime,
    grace_seconds: int = STEP_NULL_GRACE_SECONDS,
) -> bool:
    """A run is stuck only when its current_task_id is NULL beyond the grace
    window (the lock-free submit window crashed before persisting the task id).
    A non-terminal but long-running task is left to the reconciler, which will
    flip it to a terminal status that terminal_action() then handles."""
    if current_task_id is not None or step_started_at is None:
        return False
    return now - step_started_at > timedelta(seconds=grace_seconds)


def _resolve_step_timeout(
    body: dict[str, Any] | None, config_snapshot: dict[str, Any] | None
) -> int:
    """Best per-task upper-bound timeout for the in-flight step task.

    No dedicated resolved-timeout column is persisted, so we reconstruct it from
    what the tasks row carries: an explicit per-task request (``body.limits
    .timeout_seconds``) → the container config snapshot override
    (``config_snapshot.timeout_seconds``) → the platform default ceiling. The
    real resolved timeout (resolve_limits) is always <= the tenant ceiling, so
    this is a guaranteed upper bound — a run can never hang forever."""
    limits = (body or {}).get("limits") or {}
    requested = limits.get("timeout_seconds")
    if requested is not None:
        return int(requested)
    override = (config_snapshot or {}).get("timeout_seconds")
    if override is not None:
        return int(override)
    return STEP_DEFAULT_TIMEOUT_SECONDS


def _step_timed_out(
    step_started_at: datetime | None,
    timeout_seconds: int | None,
    now: datetime,
    grace_seconds: int = STEP_TIMEOUT_GRACE_SECONDS,
) -> bool:
    """True when a non-terminal step task has been in flight past its resolved
    timeout + grace. Guards the case the reconciler can't see: a step task on a
    HEALTHY container whose ingestion coroutine died stays `running` forever."""
    if step_started_at is None or timeout_seconds is None:
        return False
    return now - step_started_at > timedelta(seconds=timeout_seconds + grace_seconds)


# --- step submission ---------------------------------------------------------
async def _load_prompt(session: Any, tenant_id: str, pid: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(prompts.c.body, prompts.c.variables).where(
                prompts.c.id == pid, prompts.c.tenant_id == tenant_id
            )
        )
    ).mappings().first()
    return dict(row) if row is not None else None


async def submit_step(
    session: Any,
    *,
    settings: Any,
    session_factory: Any,
    docker_client: Any,
    shim_dispatcher: Any,
    tenant_id: str,
    step: dict[str, Any],
    step_index: int,
    workflow_id: str,
    run_id: str,
) -> str:
    """Resolve a step's prompt + variables and submit it to the step's container,
    returning the new task id. Network I/O happens here, never under a row lock."""
    prompt = await _load_prompt(session, tenant_id, step["prompt_id"])
    if prompt is None:
        raise ValueError(f"step {step_index}: prompt {step['prompt_id']} not found")
    text = resolve_body(prompt["body"], step.get("variables"), prompt.get("variables"))
    result = await submit_task_core(
        session,
        settings=settings,
        session_factory=session_factory,
        docker_client=docker_client,
        shim_dispatcher=shim_dispatcher,
        tenant_id=tenant_id,
        cid=step["container_id"],
        body=TaskBody(
            prompt=text,
            metadata={
                "workflow_id": workflow_id,
                "workflow_run_id": run_id,
                "workflow_step": step_index,
            },
        ),
    )
    return result["task_id"]


async def start_run(
    session: Any,
    *,
    settings: Any,
    session_factory: Any,
    docker_client: Any,
    shim_dispatcher: Any,
    tenant_id: str,
    workflow: dict[str, Any],
    trigger_source: str,
    scheduled_task_id: str | None = None,
) -> str:
    """Atomic run start: submit step 0 FIRST, then insert the run row with
    current_task_id already populated, in one commit. If the step-0 submit
    raises, no run row is written (the exception propagates to the caller)."""
    steps = workflow["steps"]
    run_id = new_workflow_run_id()
    task_id = await submit_step(
        session,
        settings=settings,
        session_factory=session_factory,
        docker_client=docker_client,
        shim_dispatcher=shim_dispatcher,
        tenant_id=tenant_id,
        step=steps[0],
        step_index=0,
        workflow_id=workflow["id"],
        run_id=run_id,
    )
    now = datetime.now(UTC)
    timeline = init_timeline(steps)
    timeline = mark_running(timeline, 0, started_at=now)
    timeline = mark_task(timeline, 0, task_id)
    await session.execute(
        workflow_runs.insert().values(
            id=run_id,
            workflow_id=workflow["id"],
            tenant_id=tenant_id,
            status="running",
            cursor=0,
            current_task_id=task_id,
            step_count=len(steps),
            trigger_source=trigger_source,
            scheduled_task_id=scheduled_task_id,
            started_at=now,
            step_started_at=now,
            steps=timeline,
        )
    )
    await _emit_workflow_event(
        session, run_id, "started",
        {
            "workflow_id": workflow["id"],
            "step_count": len(steps),
            "trigger_source": trigger_source,
            "task_id": task_id,
            "step": 0,
        },
    )
    await session.commit()
    return run_id


# --- DB-apply helpers (factored out so tests can monkeypatch them) -----------
async def _claim_active_runs(db: Any) -> list[Any]:
    return (
        await db.execute(
            sa.select(workflow_runs)
            .where(workflow_runs.c.status == "running")
            .with_for_update(skip_locked=True)
        )
    ).all()


async def _task_status(db: Any, task_id: str | None) -> tuple[str | None, int | None]:
    """Read the in-flight step task's (status, resolved upper-bound timeout).

    Returns ``(None, None)`` when there is no task id or the row is missing. The
    timeout is reconstructed from the persisted body/config_snapshot so the claim
    phase can bound a stuck non-terminal task (see ``_step_timed_out``)."""
    if task_id is None:
        return None, None
    row = (
        await db.execute(
            sa.select(tasks.c.status, tasks.c.body, tasks.c.config_snapshot).where(
                tasks.c.id == task_id
            )
        )
    ).mappings().first()
    if row is None:
        return None, None
    return row["status"], _resolve_step_timeout(row["body"], row["config_snapshot"])


async def _emit_workflow_event(
    db: Any, run_id: str, type_: str, payload: dict[str, Any]
) -> None:
    """Append one event to workflow_events with the next per-run seq.

    Seq is allocated in-SQL (COALESCE(MAX(seq),0)+1 scoped to the run) so it is
    race-free while the run row is held FOR UPDATE during the claim phase. The
    (run_id, seq) PK + on_conflict_do_nothing is a backstop."""
    next_seq = (
        sa.select(sa.func.coalesce(sa.func.max(workflow_events.c.seq), 0) + 1)
        .where(workflow_events.c.run_id == run_id)
        .scalar_subquery()
    )
    stmt = (
        pg_insert(workflow_events)
        .values(run_id=run_id, seq=next_seq, type=type_, payload=payload)
        .on_conflict_do_nothing(index_elements=["run_id", "seq"])
    )
    await db.execute(stmt)


async def _apply_run_update(
    db: Any,
    run_id: str,
    values: dict[str, Any],
    *,
    commit: bool = True,
    event: tuple[str, dict[str, Any]] | None = None,
) -> None:
    await db.execute(
        workflow_runs.update().where(workflow_runs.c.id == run_id).values(**values)
    )
    if event is not None:
        await _emit_workflow_event(db, run_id, event[0], event[1])
    if commit:
        await db.commit()


async def _load_workflow_steps(
    db: Any, tenant_id: str, workflow_id: str
) -> list[dict[str, Any]]:
    row = (
        await db.execute(
            sa.select(workflows.c.steps).where(
                workflows.c.id == workflow_id, workflows.c.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    return list(row or [])


async def _fail_run(
    db: Any,
    run_id: Any,
    steps: list[dict[str, Any]] | None,
    error_step: int,
    message: str,
    now: datetime,
    *,
    commit: bool = True,
) -> None:
    """Stage/apply the terminal 'failed' update shared by every fail path."""
    vals: dict[str, Any] = {
        "status": "failed",
        "error_step": error_step,
        "error_message": message,
        "ended_at": now,
    }
    if steps is not None:
        vals["steps"] = mark_failed(steps, error_step, now)
    await _apply_run_update(
        db, run_id, vals, commit=commit,
        event=("failed", {"error_step": error_step, "error_message": message}),
    )


async def advance_workflow_runs(
    db: Any,
    docker_client: Any,
    shim: Any,
    *,
    settings: Any,
    session_factory: Any,
) -> None:
    """One sweep tick over active workflow_runs: claim -> commit -> submit.

    Claim phase: in a single short transaction, lock running runs FOR UPDATE
    SKIP LOCKED, decide each transition, and stage the cursor-advance / terminal
    bookkeeping (commit=False). A single db.commit() then releases ALL locks.
    Submit phase (no lock held): submit any advanced steps to their containers
    and persist the new current_task_id in their own short transactions."""
    now = datetime.now(UTC)
    runs = await _claim_active_runs(db)
    if not runs:
        return

    # --- Claim phase: decide + stage bookkeeping under the lock. -------------
    to_submit: list[tuple[Any, int, list[dict[str, Any]] | None]] = []
    for run in runs:
        status, timeout_seconds = await _task_status(db, run.current_task_id)
        if status is None and is_stuck(run.current_task_id, run.step_started_at, now):
            await _fail_run(
                db, run.id, run.steps, run.cursor, "step stuck/orphaned", now,
                commit=False,
            )
            continue
        action = terminal_action(run.cursor, run.step_count, status or "running")
        if action == "wait":
            # A non-terminal task with a known current_task_id is normally left to
            # the reconciler; only step-timeout past grace forces a fail here.
            if run.current_task_id is not None and _step_timed_out(
                run.step_started_at, timeout_seconds, now
            ):
                await _fail_run(
                    db, run.id, run.steps, run.cursor, "step timed out / stuck", now,
                    commit=False,
                )
            continue
        if action == "complete":
            vals = {"status": "completed", "ended_at": now, "current_task_id": None}
            if run.steps is not None:
                vals["steps"] = mark_completed(run.steps, run.cursor, now)
            await _apply_run_update(
                db, run.id, vals, commit=False,
                event=("completed", {"step_count": run.step_count}),
            )
        elif action == "fail":
            await _fail_run(
                db, run.id, run.steps, run.cursor, "step task failed", now,
                commit=False,
            )
        elif action == "advance":
            next_cursor = run.cursor + 1
            tl = run.steps
            staged = {
                "cursor": next_cursor,
                "current_task_id": None,
                "step_started_at": now,
            }
            if tl is not None:
                tl = mark_completed(tl, run.cursor, now)
                staged["steps"] = tl
            await _apply_run_update(db, run.id, staged, commit=False)
            to_submit.append((run, next_cursor, tl))
    await db.commit()  # release locks BEFORE any submit I/O

    # --- Submit phase: no lock held. ----------------------------------------
    for run, next_cursor, tl in to_submit:
        steps = await _load_workflow_steps(db, run.tenant_id, run.workflow_id)
        if next_cursor >= len(steps):  # steps trimmed mid-run -> complete cleanly
            await _apply_run_update(
                db,
                run.id,
                {"status": "completed", "ended_at": now, "current_task_id": None},
                event=("completed", {"step_count": run.step_count}),
            )
            continue
        try:
            task_id = await submit_step(
                db,
                settings=settings,
                session_factory=session_factory,
                docker_client=docker_client,
                shim_dispatcher=shim,
                tenant_id=run.tenant_id,
                step=steps[next_cursor],
                step_index=next_cursor,
                workflow_id=run.workflow_id,
                run_id=run.id,
            )
        except Exception as exc:  # noqa: BLE001 — stop the run on any submit failure
            await _fail_run(db, run.id, tl, next_cursor, str(exc), now)
            continue
        vals: dict[str, Any] = {"current_task_id": task_id}
        if tl is not None:
            tl2 = mark_running(
                tl, next_cursor, started_at=now,
                container_id=steps[next_cursor].get("container_id"),
            )
            vals["steps"] = mark_task(tl2, next_cursor, task_id)
        await _apply_run_update(
            db, run.id, vals,
            event=("step_advanced", {
                "from_step": next_cursor - 1,
                "to_step": next_cursor,
                "task_id": task_id,
            }),
        )

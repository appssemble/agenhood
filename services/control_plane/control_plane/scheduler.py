"""Background sweep that fires due scheduled tasks.

Registered in app.py's lifespan via _bg_loop. Each tick claims every schedule
whose next_run_at has elapsed (FOR UPDATE SKIP LOCKED), advances their next_run_at
in a single committed "claim" transaction, then fires each claimed task — either
by submitting a prompt task via submit_task_core (prompt target) or starting a
workflow run via start_run (workflow target, with overlap guard).

Claim-then-fire ordering matters: once a row's next_run_at is advanced and
committed, it is no longer due, so neither a crash mid-submit nor a second
control-plane replica can re-fire the same slot. Because the claim commit happens
before any submit, releasing the SKIP LOCKED row locks is harmless — every claimed
row is already in the future.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from agentcore.models import TaskBody
from control_plane.models_db import prompts, scheduled_tasks, workflow_runs, workflows
from control_plane.prompts_service import resolve_body
from control_plane.routers.tasks import submit_task_core
from control_plane.scheduling import compute_next_run
from control_plane.workflow_engine import advance_workflow_runs, start_run

log = logging.getLogger("scheduler")

_SCHEDULER_INTERVAL = 30  # seconds


def _advance_values(schedule: dict, timezone: str, now: datetime) -> dict[str, Any]:
    """The next_run_at advance for a fired schedule. 'once' disables; recurring
    moves to the next slot strictly after `now` (coalescing missed runs)."""
    values: dict[str, Any] = {
        "next_run_at": compute_next_run(schedule, timezone, now),
        "updated_at": now,
    }
    if schedule.get("kind") == "once":
        values["enabled"] = False
    return values


async def _apply_schedule_update(session: Any, sid: str, values: dict[str, Any]) -> None:
    await session.execute(
        scheduled_tasks.update().where(scheduled_tasks.c.id == sid).values(**values)
    )
    await session.commit()


# --- per-kind fire helpers (extracted so tests can monkeypatch them) ----------

async def _load_prompt_row(
    session: Any, tenant_id: str, prompt_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(prompts.c.body, prompts.c.variables).where(
                prompts.c.id == prompt_id,
                prompts.c.tenant_id == tenant_id,
            )
        )
    ).mappings().first()
    return dict(row) if row is not None else None


async def _workflow_overlap_exists(session: Any, scheduled_task_id: str) -> bool:
    """Return True if a workflow_run for this scheduled_task_id is still running."""
    row = (
        await session.execute(
            sa.select(sa.literal(1)).select_from(workflow_runs).where(
                workflow_runs.c.scheduled_task_id == scheduled_task_id,
                workflow_runs.c.status == "running",
            )
        )
    ).first()
    return row is not None


async def _load_workflow_row(
    session: Any, tenant_id: str, workflow_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(workflows.c.id, workflows.c.steps).where(
                workflows.c.id == workflow_id,
                workflows.c.tenant_id == tenant_id,
            )
        )
    ).mappings().first()
    return dict(row) if row is not None else None


async def _submit_due_schedule(
    *,
    session: Any,
    row: Any,
    now: datetime,
    settings: Any,
    session_factory: Any,
    docker_client: Any,
    shim_dispatcher: Any,
) -> None:
    """Fire an already-claimed schedule and record the outcome.

    Branches on ``row.target["kind"]``:
    - **prompt**: resolve prompt body + variables, submit via submit_task_core.
    - **workflow**: skip (skipped_overlap) if a run is already active; otherwise
      start a new run via start_run.

    The schedule's next_run_at was advanced+committed in the claim phase, so a
    failure here never re-fires the slot."""
    target = row.target
    kind = target.get("kind")
    last_status = "submitted"
    last_run_ref: str | None = None

    try:
        if kind == "prompt":
            prompt_row = await _load_prompt_row(session, row.tenant_id, target["prompt_id"])
            if prompt_row is None:
                raise ValueError(f"prompt {target['prompt_id']} not found")
            resolved = resolve_body(
                prompt_row["body"],
                target.get("variables"),
                prompt_row.get("variables"),
            )
            result = await submit_task_core(
                session,
                settings=settings,
                session_factory=session_factory,
                docker_client=docker_client,
                shim_dispatcher=shim_dispatcher,
                tenant_id=row.tenant_id,
                cid=target["container_id"],
                body=TaskBody(
                    prompt=resolved,
                    metadata={"scheduled_task_id": row.id},
                ),
            )
            last_run_ref = result.get("task_id")

        elif kind == "workflow":
            if await _workflow_overlap_exists(session, row.id):
                # An active run for this schedule is already running — skip.
                last_status = "skipped_overlap"
            else:
                wf_row = await _load_workflow_row(session, row.tenant_id, target["workflow_id"])
                if wf_row is None:
                    raise ValueError(f"workflow {target['workflow_id']} not found")
                run_id = await start_run(
                    session,
                    settings=settings,
                    session_factory=session_factory,
                    docker_client=docker_client,
                    shim_dispatcher=shim_dispatcher,
                    tenant_id=row.tenant_id,
                    workflow=wf_row,
                    trigger_source="schedule",
                    scheduled_task_id=row.id,
                )
                last_run_ref = run_id

        else:
            raise ValueError(f"unknown target kind: {kind!r}")

    except Exception as exc:  # noqa: BLE001 — record the failure, keep the schedule
        last_status = "failed"
        log.warning("scheduled task %s failed to submit: %s", row.id, exc)

    await _apply_schedule_update(
        session, row.id,
        {"last_run_at": now, "last_run_ref": last_run_ref, "last_status": last_status},
    )


async def scheduler_sweep(
    db: Any,
    docker_client: Any,
    shim: Any,
    *,
    settings: Any,
    session_factory: Any,
) -> None:
    """One sweep tick: claim every due schedule (advance + single commit), then
    fire each claimed task."""
    # Phase B (advance in-flight workflow runs) runs BEFORE Phase A (fire due
    # schedules) so a run that finishes this tick frees its overlap lock and a
    # freshly-due schedule can fire in the same tick.
    try:
        await advance_workflow_runs(
            db, docker_client, shim, settings=settings, session_factory=session_factory)
    except Exception:  # noqa: BLE001 — a Phase B failure must never skip Phase A
        log.exception("scheduler: advance_workflow_runs (Phase B) failed")
    now = datetime.now(UTC)
    due = (
        await db.execute(
            sa.select(scheduled_tasks)
            .where(
                scheduled_tasks.c.enabled.is_(True),
                scheduled_tasks.c.next_run_at.isnot(None),
                scheduled_tasks.c.next_run_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not due:
        return

    # Claim phase: advance every due row's next_run_at, then a SINGLE commit.
    # After this commit no row is due, so releasing the SKIP LOCKED locks is safe
    # and a second replica cannot re-claim the same slots.
    for row in due:
        await db.execute(
            scheduled_tasks.update()
            .where(scheduled_tasks.c.id == row.id)
            .values(**_advance_values(row.schedule, row.timezone, now))
        )
    await db.commit()

    # Fire phase: submit each claimed task. One failure can't kill the sweep.
    for row in due:
        try:
            await _submit_due_schedule(
                session=db, row=row, now=now, settings=settings,
                session_factory=session_factory, docker_client=docker_client,
                shim_dispatcher=shim,
            )
        except Exception:  # noqa: BLE001 — never let one schedule kill the sweep
            log.exception("scheduler: failed firing schedule %s", getattr(row, "id", "?"))

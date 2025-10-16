"""Idle-pause sweep (spec §4.8): the first dormancy tier (running → paused).

A background loop runs every minute and selects *candidates* — running containers
that have been idle longer than their tenant's ``idle_pause_minutes`` and have no
in-flight tasks — then pauses each through the guarded pause path (§4.10).

The candidate query is only a filter, not the decision: the no-active-tasks check
is racy on its own (a task can be submitted between the query and the stop).
``lifecycle.pause`` re-checks for in-flight tasks *under the container lock* and
only stops the container if the ``running → pausing`` CAS succeeds, which closes
the idle-pause/submit race (spec §4.8).

Idle is measured from ``GREATEST(created_at, last_task_at, status_changed_at)`` —
the most recent of provisioning, the last task start, and the last status change.
This keeps a never-run container (NULL ``last_task_at``) and a just-resumed one
(stale ``last_task_at`` but fresh ``status_changed_at`` from the ``→running``
transition) out of the candidate set until they are genuinely idle.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import lifecycle
from control_plane.errors import APIError
from control_plane.lifecycle import _Executable as _DB

log = logging.getLogger("idle")

# spec §4.8: default idle threshold when a tenant sets no idle_pause_minutes.
_DEFAULT_IDLE_PAUSE_MINUTES = 20

# Postgres deadlock_detected — transient by design, so the victim retries once.
_DEADLOCK_SQLSTATE = "40P01"


def _is_deadlock(exc: BaseException) -> bool:
    """True if *exc* is (or wraps, via ``.orig``) a Postgres deadlock (40P01)."""
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == _DEADLOCK_SQLSTATE


async def _idle_candidates(db: _DB) -> list[str]:
    """Running containers idle past their tenant's idle_pause_minutes, no in-flight
    tasks (spec §4.8). Uses idx_containers_idle (status, last_task_at)."""
    res = await db.execute(
        text(
            "SELECT c.id FROM containers c JOIN tenants t ON t.id = c.tenant_id "
            "WHERE c.status = 'running' "
            "AND GREATEST(c.created_at, c.last_task_at, c.status_changed_at) "
            "    < now() - make_interval(mins => COALESCE("
            f"      (t.limits->>'idle_pause_minutes')::int, {_DEFAULT_IDLE_PAUSE_MINUTES})) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM tasks tk "
            "  WHERE tk.container_id = c.id AND tk.status IN ('pending','running')"
            ")"
        )
    )
    return [r[0] for r in res.fetchall()]


async def idle_pause_sweep(
    db: AsyncSession, docker_client: object, shim: object = None
) -> None:
    """Pause each eligible idle container via the guarded pause path (spec §4.8).

    Each pause is its own transaction: ``lifecycle.pause`` commits the
    running→pausing→paused transitions itself (so the container-row lock is not
    held across the docker stop), and the trailing ``commit()`` here is a harmless
    no-op. On the benign 409 race — or any unexpected failure — roll back so a
    poisoned transaction does not cascade into the remaining candidates. A
    transient Postgres deadlock (40P01) on a candidate is retried once before the
    sweep moves on.
    """
    for cid in await _idle_candidates(db):
        for attempt in (1, 2):  # one retry on a transient deadlock
            try:
                await lifecycle.pause(db, docker_client, shim, cid)
                await db.commit()
                break
            except APIError:
                # Benign race: a task slipped in after the candidate query, so the
                # guarded pause 409s under the lock. Leave the container running.
                await db.rollback()
                break
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                if attempt == 1 and _is_deadlock(exc):
                    log.warning("idle pause deadlock for %s; retrying once", cid)
                    continue
                log.exception("idle pause sweep failed for %s", cid)
                break

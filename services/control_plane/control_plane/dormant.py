"""Dormant-tier sweeps: archive (paused→archived) and reclaim (archived→destroyed).

Spec §4.13:
- archive_sweep: picks paused rows older than the tenant's archive_after_hours and
  archives them via the guarded lifecycle.archive op.
- reclaim_sweep: picks archived rows older than the tenant's reclaim_after_days and
  destroys the workspace volume (archived → destroying → destroyed).

Both candidate queries key off status_changed_at via idx_containers_dormant.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import docker_ctl, lifecycle
from control_plane.audit import audit
from control_plane.lifecycle import _Executable as _DB

log = logging.getLogger("dormant")


async def _archive_candidates(db: _DB) -> list[str]:
    """paused longer than the tenant's archive_after_hours (spec §4.13).
    Uses idx_containers_dormant (status, status_changed_at)."""
    res = await db.execute(
        text(
            "SELECT c.id FROM containers c JOIN tenants t ON t.id = c.tenant_id "
            "WHERE c.status = 'paused' "
            "AND c.status_changed_at < now() - make_interval("
            "  hours => COALESCE((t.limits->>'archive_after_hours')::int, 72))"
        )
    )
    return [r[0] for r in res.fetchall()]


async def _reclaim_candidates(db: _DB) -> list[str]:
    """archived longer than the tenant's reclaim_after_days (spec §4.13)."""
    res = await db.execute(
        text(
            "SELECT c.id FROM containers c JOIN tenants t ON t.id = c.tenant_id "
            "WHERE c.status = 'archived' "
            "AND c.status_changed_at < now() - make_interval("
            "  days => COALESCE((t.limits->>'reclaim_after_days')::int, 30))"
        )
    )
    return [r[0] for r in res.fetchall()]


async def archive_sweep(db: AsyncSession, docker_client: object, shim: object = None) -> None:
    """Archive each eligible paused container (spec §4.13).

    Each archive is committed individually: the guarded op transitions the row
    paused→archiving→archived with in-session UPDATEs, so without a commit the
    transition rolls back when the sweep's session closes. Roll back on failure so a
    poisoned transaction does not cascade into the remaining candidates.
    """
    for cid in await _archive_candidates(db):
        try:
            await lifecycle.archive(db, docker_client, cid)  # guarded: paused→archiving→archived
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("archive sweep failed for %s", cid)


async def reclaim_one(db: _DB, docker_client: object, cid: str) -> None:
    """archived → destroying → destroyed; delete the workspace volume (spec §4.13).

    Writes a container.reclaim audit row on successful completion.
    """
    async with lifecycle.container_lock(cid):
        if not await lifecycle.transition(db, cid, "archived", "destroying"):
            return
        await lifecycle._set(db, cid, destroy_delete_volume=True)
        row = await lifecycle._load(db, cid)
        await docker_ctl.volume_rm(docker_client, row["volume_name"])
        await lifecycle.transition(db, cid, "destroying", "destroyed")
    await audit(
        db,
        actor_type="system",
        action="container.reclaim",
        target_type="container",
        target_id=cid,
        details={"volume_name": row["volume_name"]},
    )


async def reclaim_sweep(db: AsyncSession, docker_client: object, shim: object = None) -> None:
    """Reclaim each eligible archived container's volume (spec §4.13).

    Each reclaim is committed individually (archived→destroying→destroyed + the
    reclaim audit row); without a commit the work rolls back when the sweep's session
    closes. Roll back on failure so a poisoned transaction does not cascade.
    """
    for cid in await _reclaim_candidates(db):
        try:
            await reclaim_one(db, docker_client, cid)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("reclaim sweep failed for %s", cid)

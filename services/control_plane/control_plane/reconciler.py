"""Reconciler: decision function (pure) + executor + startup/periodic wiring.

§4.11 of the agent-runtime spec.  The decision function maps
(db_status, DockerStateInfo) → ReconcileAction with no I/O so every row of
the decision table can be unit-tested without docker or postgres.  The
executor applies actions via the guarded lifecycle ops.
"""
from __future__ import annotations

import asyncio
import enum
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import docker_ctl, lifecycle
from control_plane.audit import audit
from control_plane.docker_ctl import DockerStateInfo
from control_plane.lifecycle import _Executable as _DB

log = logging.getLogger("reconciler")


# ---------------------------------------------------------------------------
# Action enum — one value per cell in the spec §4.11 decision table
# ---------------------------------------------------------------------------

class ReconcileAction(enum.Enum):
    NOOP = "noop"  # consistent; nothing to do
    ADOPT_RUNNING = "adopt_running"  # re-arm health probe; status stays/becomes running
    RECOVER = "recover"  # enter the recovery routine (§4.12)
    SET_PAUSED = "set_paused"  # container down + volume present → paused (no docker change)
    SET_ERROR = "set_error"  # unrecoverable (e.g. missing container + missing volume)
    STOP_TO_PAUSED = "stop_to_paused"  # /shutdown + docker stop, then → paused
    FINISH_TO_RUNNING = "finish_to_running"  # interrupted provision/resume up & ready → running
    FINISH_TO_PAUSED = "finish_to_paused"  # interrupted pause whose container exited → paused
    DESTROY_PARTIAL_TO_ERROR = "destroy_partial_to_error"  # provisioning never completed → error
    RM_TO_ARCHIVED = "rm_to_archived"  # interrupted archive: rm stopped container → archived
    SET_ARCHIVED = "set_archived"  # archive whose container already gone → archived
    RM_STALE_STAY_ARCHIVED = "rm_stale_stay_archived"  # stale container → rm, stay archived
    FINISH_DESTROY = "finish_destroy"  # finish a destroy from the persisted intent → destroyed
    FINISH_DELETE = "finish_delete"  # finish an interrupted hard delete → row removed


# ---------------------------------------------------------------------------
# Pure decision function — spec §4.11 decision table
# ---------------------------------------------------------------------------

def reconcile_decision(
    db_status: str,
    docker: DockerStateInfo,
    *,
    readyz_ok: bool,
    volume_exists: bool,
) -> ReconcileAction:
    """Pure mapping of (db_status, docker_state) → action, exactly per spec §4.11.

    `readyz_ok` is the result of a /readyz probe when the container is up (else False).
    `volume_exists` reflects whether the workspace volume is present.
    """
    up = docker.present and docker.status == "running"
    down = docker.present and docker.status in ("exited", "created", "dead")

    if db_status == "running":
        if up and readyz_ok:
            return ReconcileAction.ADOPT_RUNNING
        if up and not readyz_ok:
            return ReconcileAction.RECOVER
        if down:
            # clean exit + volume → paused; OOM or non-zero exit → recover
            if not docker.oom_killed and (docker.exit_code in (0, None)) and volume_exists:
                return ReconcileAction.SET_PAUSED
            return ReconcileAction.RECOVER
        # missing
        return ReconcileAction.RECOVER if volume_exists else ReconcileAction.SET_ERROR

    if db_status == "paused":
        if down:
            return ReconcileAction.NOOP
        if up:
            return ReconcileAction.ADOPT_RUNNING if readyz_ok else ReconcileAction.STOP_TO_PAUSED
        # missing: volume remains; paused/missing is consistent safe-rest
        return ReconcileAction.NOOP

    if db_status == "provisioning":
        if up and readyz_ok:
            return ReconcileAction.FINISH_TO_RUNNING
        return ReconcileAction.DESTROY_PARTIAL_TO_ERROR  # up-not-ready / exited / missing

    if db_status == "resuming":
        if up and readyz_ok:
            return ReconcileAction.FINISH_TO_RUNNING
        return ReconcileAction.SET_PAUSED  # exited / not ready → safe rest

    if db_status == "pausing":
        if down:
            return ReconcileAction.FINISH_TO_PAUSED
        return ReconcileAction.STOP_TO_PAUSED  # up → re-issue stop

    if db_status == "archiving":
        return ReconcileAction.RM_TO_ARCHIVED if docker.present else ReconcileAction.SET_ARCHIVED

    if db_status == "archived":
        return ReconcileAction.RM_STALE_STAY_ARCHIVED if docker.present else ReconcileAction.NOOP

    if db_status == "recovering":
        return ReconcileAction.RECOVER

    if db_status == "destroying":
        return ReconcileAction.FINISH_DESTROY

    if db_status == "deleting":
        return ReconcileAction.FINISH_DELETE

    if db_status == "error":
        return ReconcileAction.NOOP

    return ReconcileAction.NOOP


# ---------------------------------------------------------------------------
# Executor helpers
# ---------------------------------------------------------------------------

async def _volume_exists(docker_client: object, volume_name: str) -> bool:
    """Check whether a named Docker volume exists."""
    import docker.errors  # noqa: PLC0415

    def _check() -> bool:
        try:
            docker_client.volumes.get(volume_name)  # type: ignore[attr-defined]
            return True
        except docker.errors.NotFound:
            return False

    return await asyncio.to_thread(_check)


async def apply_action(
    *,
    db: _DB,
    docker_client: object,
    shim: object,
    cid: str,
    action: ReconcileAction,
    row: dict[str, object],
    settings: object | None = None,
) -> None:
    """Execute one reconcile action under the container lock.  Idempotent.

    All transitions go through the guarded lifecycle helpers (never raw UPDATEs)
    so the legal-transition table is always enforced.  When the reconciler moves
    a row to `error` or forces recovery it writes a `container.reconciled`
    audit row with details={'from', 'docker', 'to'}.
    """
    dn = str(row.get("docker_name", cid))

    # RECOVER cannot run inside the container lock because recover() re-acquires it.
    if action == ReconcileAction.RECOVER:
        old_status = str(row.get("status", "unknown"))
        docker_status = str(row.get("_docker_status", "unknown"))
        await lifecycle.recover(db, docker_client, shim, cid, settings=settings)
        await audit(
            db,
            actor_type="system",
            action="container.reconciled",
            target_type="container",
            target_id=cid,
            details={"from": old_status, "docker": docker_status, "to": "recovering"},
        )
        return

    async with lifecycle.container_lock(cid):
        if action == ReconcileAction.NOOP:
            return

        if action == ReconcileAction.ADOPT_RUNNING:
            # Adopt only a paused row back to running. An already-running row needs
            # no change, and must NOT be re-affirmed: transition_from_any rewrites
            # status_changed_at=now() on every match, and idle.py keys the idle
            # clock off GREATEST(..., status_changed_at). Accepting "running" here
            # would reset that clock every reconcile pass (180s), so a healthy idle
            # container could never age to its idle_pause_minutes and never pause.
            await lifecycle.transition_from_any(db, cid, {"paused"}, "running")
            return

        if action == ReconcileAction.SET_PAUSED:
            await lifecycle.transition_from_any(db, cid, {"running", "resuming"}, "paused")
            return

        if action == ReconcileAction.SET_ERROR:
            old_status = str(row.get("status", "unknown"))
            docker_status = str(row.get("_docker_status", "unknown"))
            await lifecycle.transition_from_any(db, cid, {"running", "provisioning"}, "error")
            await lifecycle._set(db, cid, error_message="container and volume missing on reconcile")
            await lifecycle.fail_tasks(db, cid, code="container_restarted")
            await audit(
                db,
                actor_type="system",
                action="container.reconciled",
                target_type="container",
                target_id=cid,
                details={"from": old_status, "docker": docker_status, "to": "error"},
            )
            return

        if action == ReconcileAction.STOP_TO_PAUSED:
            try:
                await shim.post(cid, "/shutdown", best_effort=True)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            await docker_ctl.stop(docker_client, dn, lifecycle.STOP_GRACE_SECONDS)
            await lifecycle.transition_from_any(db, cid, {"paused", "pausing"}, "paused")
            return

        if action == ReconcileAction.FINISH_TO_RUNNING:
            await lifecycle.transition_from_any(db, cid, {"provisioning", "resuming"}, "running")
            return

        if action == ReconcileAction.FINISH_TO_PAUSED:
            await lifecycle.transition_from_any(db, cid, {"pausing"}, "paused")
            return

        if action == ReconcileAction.DESTROY_PARTIAL_TO_ERROR:
            old_status = str(row.get("status", "unknown"))
            docker_status = str(row.get("_docker_status", "unknown"))
            await docker_ctl.rm(docker_client, dn)   # remove partial container; keep volume
            await lifecycle.transition_from_any(db, cid, {"provisioning"}, "error")
            await lifecycle._set(db, cid, error_message="provisioning interrupted")
            await audit(
                db,
                actor_type="system",
                action="container.reconciled",
                target_type="container",
                target_id=cid,
                details={"from": old_status, "docker": docker_status, "to": "error"},
            )
            return

        if action == ReconcileAction.RM_TO_ARCHIVED:
            await docker_ctl.rm(docker_client, dn)
            await lifecycle.transition_from_any(db, cid, {"archiving"}, "archived")
            return

        if action == ReconcileAction.SET_ARCHIVED:
            await lifecycle.transition_from_any(db, cid, {"archiving"}, "archived")
            return

        if action == ReconcileAction.RM_STALE_STAY_ARCHIVED:
            await docker_ctl.rm(docker_client, dn)  # status stays archived
            return

        if action == ReconcileAction.FINISH_DESTROY:
            intent = row.get("destroy_delete_volume")
            await docker_ctl.rm(docker_client, dn)
            if intent is True:
                await docker_ctl.volume_rm(docker_client, str(row.get("volume_name", "")))
            elif intent is None:
                log.warning(
                    "destroy intent NULL for %s; preserving volume for operator review", cid
                )
            await lifecycle.transition_from_any(db, cid, {"destroying"}, "destroyed")
            old_status = str(row.get("status", "unknown"))
            docker_status = str(row.get("_docker_status", "unknown"))
            await audit(
                db,
                actor_type="system",
                action="container.reconciled",
                target_type="container",
                target_id=cid,
                details={"from": old_status, "docker": docker_status, "to": "destroyed"},
            )
            return

        if action == ReconcileAction.FINISH_DELETE:
            await docker_ctl.rm(docker_client, dn)
            await docker_ctl.volume_rm(docker_client, str(row.get("volume_name", "")))
            await db.execute(
                text("DELETE FROM tasks WHERE container_id = :cid"), {"cid": cid}
            )
            await audit(
                db,
                actor_type="system",
                action="container.reconciled",
                target_type="container",
                target_id=cid,
                details={
                    "from": "deleting",
                    "docker": str(row.get("_docker_status", "unknown")),
                    "to": "deleted",
                },
            )
            await db.execute(
                text("DELETE FROM containers WHERE id = :cid"), {"cid": cid}
            )
            return


# ---------------------------------------------------------------------------
# Orphan-task reconciliation  (spec §4.11)
# ---------------------------------------------------------------------------

async def reconcile_orphan_tasks(db: _DB, healthy_running_ids: set[str]) -> None:
    """Fail any pending/running task whose container is not a healthy running one."""
    ids = list(healthy_running_ids) if healthy_running_ids else ["__none__"]
    await db.execute(
        text(
            "UPDATE tasks SET status='failed', error_code=:code, ended_at=now() "
            "WHERE status IN ('pending','running') "
            "AND container_id <> ALL(:ok)"
        ),
        {"code": "container_restarted", "ok": ids},
    )


# ---------------------------------------------------------------------------
# Full-sweep runner
# ---------------------------------------------------------------------------

async def _all_active_rows(db: _DB) -> list[dict[str, object]]:
    res = await db.execute(
        text(
            "SELECT id, tenant_id, docker_name, volume_name, image_tag, image_variant, "
            "status, destroy_delete_volume FROM containers WHERE status <> 'destroyed'"
        )
    )
    keys = [
        "id", "tenant_id", "docker_name", "volume_name",
        "image_tag", "image_variant", "status", "destroy_delete_volume",
    ]
    return [dict(zip(keys, r, strict=False)) for r in res.fetchall()]


async def reconcile_all(
    db: AsyncSession, docker_client: object, shim: object, settings: object | None = None
) -> None:
    """Full sweep (startup and periodic).  Idempotent and safe to re-run (spec §4.11).

    Each row is reconciled in its own transaction: commit on success, roll back on
    failure. A single failing action (e.g. a deadlock on the status CAS) otherwise
    aborts the shared transaction, and — because the per-row error is caught and
    logged but never rolled back — every subsequent row and the orphan-task pass
    then fail with ``InFailedSQLTransactionError``. Per-row commits also keep the
    transactions short, which reduces lock contention with concurrent API writes.
    Without any commit the whole sweep's transitions roll back when the session
    closes and nothing reconciled persists.
    """
    rows = await _all_active_rows(db)
    healthy: set[str] = set()
    for row in rows:
        cid = str(row["id"])
        docker_name = str(row["docker_name"])
        info = await docker_ctl.inspect_state(docker_client, docker_name)
        readyz_ok = False
        if info.present and info.status == "running":
            try:
                # Delegate to lifecycle._poll_readyz (monkeypatchable seam).
                await lifecycle._poll_readyz(cid, timeout_s=3)
                readyz_ok = True
            except Exception:  # noqa: BLE001
                readyz_ok = False
        vol_ok = await _volume_exists(docker_client, str(row.get("volume_name", "")))
        action = reconcile_decision(
            str(row["status"]), info, readyz_ok=readyz_ok, volume_exists=vol_ok
        )
        # Tag the row with docker state so apply_action can write meaningful audit details.
        row["_docker_status"] = info.status or "missing"
        if action == ReconcileAction.ADOPT_RUNNING and str(row["status"]) == "running":
            healthy.add(cid)
        try:
            await apply_action(
                db=db,
                docker_client=docker_client,
                shim=shim,
                cid=cid,
                action=action,
                row=row,
                settings=settings,
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("reconcile action %s failed for %s", action, cid)
    try:
        await reconcile_orphan_tasks(db, healthy)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("reconcile orphan-task pass failed")


async def periodic_sweep(
    db: AsyncSession, docker_client: object, shim: object, settings: object | None = None
) -> None:
    """Lightweight version of reconcile_all for the periodic loop (spec §4.11 last paragraph)."""
    await reconcile_all(db, docker_client, shim, settings=settings)

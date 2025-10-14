from __future__ import annotations

import asyncio
import weakref
from typing import Any, Protocol

from sqlalchemy import text

from control_plane import admission, docker_ctl
from control_plane.audit import audit
from control_plane.errors import APIError, api_error

# ---- constants (spec §4.7/§4.10/§4.12) ----------------------------------------
STOP_GRACE_SECONDS = 15
READYZ_TIMEOUT = 30
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_BACKOFF = (5, 30, 120)


# ---- DB protocol (matches AsyncSession.execute signature) ----------------------
class _Executable(Protocol):
    async def execute(
        self, statement: Any, params: Any = None
    ) -> Any: ...  # noqa: E704


# ---- legal transition table (index §4 states; spec §4.10) ----------------------
# Destroying is allowed from any non-terminal state and is handled separately.
_LEGAL_TRANSITIONS: set[tuple[str, str]] = {
    ("provisioning", "running"),
    ("provisioning", "error"),
    ("running", "pausing"),
    ("running", "recovering"),
    ("pausing", "paused"),
    ("paused", "resuming"),
    ("paused", "archiving"),
    ("resuming", "running"),
    ("resuming", "paused"),        # reconciler safe-rest (spec §4.11)
    ("archiving", "archived"),
    ("archived", "provisioning"),  # rehydrate (spec §4.13)
    ("archived", "destroying"),    # reclaim (spec §4.13)
    ("recovering", "running"),
    ("recovering", "error"),
    ("error", "provisioning"),     # recover (spec §4.12)
    ("destroying", "destroyed"),
}
_NON_TERMINAL: set[str] = {
    "provisioning", "running", "pausing", "paused", "resuming",
    "archiving", "archived", "recovering", "error",
}
# destroy reaches 'archived' from any live state except 'archived' itself (nothing to
# archive) and 'archiving' (already in flight). Derived from _NON_TERMINAL so a new
# live state added there is automatically a valid archive source.
_ARCHIVING_SOURCES: set[str] = _NON_TERMINAL - {"archiving", "archived"}


def is_legal_transition(src: str, dst: str) -> bool:
    """Return True iff the src→dst transition is permitted by the lifecycle machine."""
    if dst == "deleting":
        return True  # delete is permitted from any state (incl. terminal 'destroyed')
    if dst == "destroying" and src in _NON_TERMINAL:
        return True
    if dst == "archiving" and src in _ARCHIVING_SOURCES:
        return True  # archive is permitted from any live, non-archiving state
    return (src, dst) in _LEGAL_TRANSITIONS


# ---- per-container async lock registry (spec §4.10) ----------------------------
_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def container_lock(cid: str) -> asyncio.Lock:
    """Return the shared asyncio.Lock for *cid*, creating it if not yet present.

    The lock is stored in a WeakValueDictionary so it is garbage-collected
    when no coroutine holds a reference (i.e. no outstanding acquire).  Two
    calls with the same *cid* in the same event-loop turn return the same
    object.
    """
    lock = _LOCKS.get(cid)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[cid] = lock
    return lock


# ---- durable CAS on status (spec §4.10) ----------------------------------------
async def transition(db: _Executable, cid: str, expected: str, new: str) -> bool:
    """Conditional UPDATE status expected→new; returns True iff exactly one row moved.

    A return value of False means another actor (coroutine or reconciler) already
    moved the row — the caller must handle this (typically 409/retry).

    The caller owns the transaction; this function does not commit.
    """
    res = await db.execute(
        text(
            "UPDATE containers "
            "SET status = :new, status_changed_at = now(), updated_at = now() "
            "WHERE id = :cid AND status = :expected"
        ),
        {"cid": cid, "expected": expected, "new": new},
    )
    return bool(res.rowcount == 1)


async def transition_from_any(
    db: _Executable, cid: str, expected: set[str], new: str
) -> bool:
    """CAS that accepts any status in *expected*; returns True iff one row moved."""
    res = await db.execute(
        text(
            "UPDATE containers "
            "SET status = :new, status_changed_at = now(), updated_at = now() "
            "WHERE id = :cid AND status = ANY(:expected)"
        ),
        {"cid": cid, "expected": list(expected), "new": new},
    )
    return bool(res.rowcount == 1)


async def current_status(db: _Executable, cid: str) -> str | None:
    """Fetch the current status of a container row."""
    res = await db.execute(
        text("SELECT status FROM containers WHERE id = :cid"),
        {"cid": cid},
    )
    row = res.first()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _load(db: _Executable, cid: str) -> dict[str, Any]:
    """Load the container row fields needed for docker_ctl ops."""
    res = await db.execute(
        text(
            "SELECT id, tenant_id, docker_name, volume_name, image_tag, image_variant, "
            "shim_token, config, resources FROM containers WHERE id = :cid"
        ),
        {"cid": cid},
    )
    row = res.first()
    if row is None:
        raise APIError(404, "not_found", f"container {cid} not found")
    keys = [
        "id", "tenant_id", "docker_name", "volume_name",
        "image_tag", "image_variant", "shim_token", "config", "resources",
    ]
    return dict(zip(keys, row, strict=False))


async def _set(db: _Executable, cid: str, **fields: Any) -> None:
    """Set arbitrary columns on a container row.

    Values that are the literal string ``'now()'`` map to the SQL ``now()``
    function; all other values are bound as parameters.
    """
    sets: list[str] = []
    params: dict[str, Any] = {"cid": cid}
    for k, v in fields.items():
        if v == "now()":
            sets.append(f"{k} = now()")
        else:
            sets.append(f"{k} = :{k}")
            params[k] = v
    sets.append("updated_at = now()")
    await db.execute(
        text(f"UPDATE containers SET {', '.join(sets)} WHERE id = :cid"),
        params,
    )


async def _await_no_active_tasks(
    db: _Executable,
    cid: str,
    *,
    timeout: float = float(STOP_GRACE_SECONDS),  # noqa: ASYNC109
) -> None:
    """Poll until in-flight task cancellation drains (best-effort, bounded)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await admission.active_task_count(db, cid) == 0:
            return
        await asyncio.sleep(0.25)
    # Bounded: proceed even if a straggler remains; docker stop will end it.


async def _poll_readyz(
    cid: str,
    *,
    timeout_s: float,
    row: dict[str, Any] | None = None,
    shim_port: int = 8080,
) -> None:
    """Poll /readyz on the container's shim until it responds 200 or timeout.

    This function is the monkeypatch seam for unit tests (which replace it with
    a no-op via ``monkeypatch.setattr(lifecycle, '_poll_readyz', ...)``).

    When *row* is provided (integration / production path), performs a real
    readiness poll against the container's shim URL:
    - Uses ``row['resources']['_host_shim_url']`` when the shim is bound to
      the host (macOS test setup).
    - Falls back to ``http://{docker_name}:{shim_port}`` otherwise.

    When *row* is None (no-op stub), returns immediately — unit tests that
    monkeypatch this function replace the whole stub, so neither branch runs.
    """
    if row is None:
        # No-op stub: unit tests monkeypatch this entire function.
        return

    from control_plane.docker_ctl.provision import _poll_readyz as _prov_poll  # noqa: PLC0415

    resources = row.get("resources") or {}
    host_shim_url = resources.get("_host_shim_url") if isinstance(resources, dict) else None
    docker_name = str(row.get("docker_name", ""))
    base_url = host_shim_url or f"http://{docker_name}:{shim_port}"
    shim_token = str(row.get("shim_token", ""))
    ready = await _prov_poll(base_url, shim_token, timeout_s)
    if not ready:
        raise RuntimeError(f"container {cid!r} shim not ready within {timeout_s}s")


# ---------------------------------------------------------------------------
# High-level lifecycle operations (spec §4.10/§4.12/§4.13)
# ---------------------------------------------------------------------------


async def pause(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    *,
    force: bool = False,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> None:
    """Guarded pause (spec §4.10/§4.13).

    Rejects a busy container with 409 unless *force*, which cancels in-flight
    tasks first. ``/shutdown`` precedes docker stop; ``STOP_GRACE_SECONDS``
    is the single grace constant used everywhere.

    Unlike the other helpers, pause **commits its own transitions** (running→
    pausing before the docker stop, then pausing→paused after) so the container-
    row write lock is never held across the slow stop. A caller's later
    ``commit()`` is then a harmless no-op.
    """
    async with container_lock(cid):
        active = await admission.active_task_count(db, cid)
        if active > 0:
            if not force:
                raise APIError(
                    409,
                    "container_not_runnable",
                    "container has in-flight tasks; pass force=True to cancel them",
                )
            await shim.cancel_all(cid)
            await _await_no_active_tasks(db, cid)
            # Audit the force-pause with the number of cancelled tasks.
            await audit(
                db,
                actor_type=actor_type,
                actor_id=actor_id,
                action="container.force_pause",
                target_type="container",
                target_id=cid,
                details={"cancelled_tasks": active},
            )

        if not await transition(db, cid, "running", "pausing"):
            return  # Another actor already moved it; back off.
        # Commit the running→pausing CAS BEFORE the slow docker stop so the
        # container-row write lock is not held across STOP_GRACE_SECONDS. Holding
        # it serialized every concurrent writer on that row, producing idle-sweep
        # Postgres deadlocks and DB-pool starvation that timed out control-plane
        # routes. The durable 'pausing' state matches the irreversible stop about
        # to happen; the reconciler completes any pause stuck in 'pausing' if the
        # stop below fails.
        await db.commit()

        try:
            await shim.post(cid, "/shutdown", best_effort=True)
        except Exception:  # noqa: BLE001
            pass  # Graceful best-effort; docker stop is the hard guarantee.

        row = await _load(db, cid)
        await docker_ctl.stop(docker_client, row["docker_name"], STOP_GRACE_SECONDS)
        await transition(db, cid, "pausing", "paused")
        await _set(db, cid, paused_at="now()")
        await db.commit()


async def resume(
    db: _Executable,
    docker_client: Any,
    cid: str,
    *,
    settings: Any = None,
) -> None:
    """Guarded resume (spec §4.10): docker start, poll /readyz."""
    async with container_lock(cid):
        if not await transition(db, cid, "paused", "resuming"):
            return
        row = await _load(db, cid)  # Now includes resources column.
        await docker_ctl.start(docker_client, row["docker_name"])
        # Docker re-assigns ephemeral host ports on every restart; update
        # resources._host_shim_url with the new binding so readyz + shim calls
        # use the correct host URL.
        _shim_port = getattr(settings, "shim_port", 8080)
        new_host_url = await docker_ctl.get_host_shim_url(
            docker_client, row["docker_name"], _shim_port
        )
        if new_host_url is not None:
            await db.execute(
                text(
                    "UPDATE containers "
                    "SET resources = COALESCE(resources, '{}') || "
                    "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                    "WHERE id = :cid"
                ),
                {"cid": cid, "url": new_host_url},
            )
            row = dict(row)
            row["resources"] = {"_host_shim_url": new_host_url}
        await _poll_readyz(
            cid,
            timeout_s=READYZ_TIMEOUT,
            row=row,
            shim_port=_shim_port,
        )
        await transition(db, cid, "resuming", "running")
        await _set(db, cid, last_active_at="now()")


async def archive(
    db: _Executable,
    docker_client: Any,
    cid: str,
) -> None:
    """Archive a paused container (spec §4.13): docker rm the stopped container, keep volume."""
    async with container_lock(cid):
        if not await transition(db, cid, "paused", "archiving"):
            return
        row = await _load(db, cid)
        await docker_ctl.rm(docker_client, row["docker_name"])  # Never touches the volume.
        await transition(db, cid, "archiving", "archived")
        await _set(db, cid, archived_at="now()")


async def rehydrate(
    db: _Executable,
    docker_client: Any,
    cid: str,
    *,
    settings: Any = None,
) -> None:
    """Rehydrate an archived container from its retained volume (spec §4.13).

    Reuses the row's docker_name / volume_name; same provisioning path as create.
    When *settings* is provided, port binding and network settings are forwarded
    to run_from_volume (required on macOS where container IPs are not routable).
    """
    async with container_lock(cid):
        if not await transition(db, cid, "archived", "provisioning"):
            return
        row = await _load(db, cid)
        host_shim_url = await docker_ctl.run_from_volume(
            docker_client,
            row,
            settings=settings,
            network=getattr(settings, "internal_network", None),
            shim_port=getattr(settings, "shim_port", None),
            bind_to_host=getattr(settings, "bind_shim_port_to_host", False),
            extra_env=getattr(settings, "agent_extra_env", None),
        )
        if host_shim_url is not None:
            # Update resources with the new host shim URL so subsequent task
            # submissions can reach the rehydrated container's shim.
            await db.execute(
                text(
                    "UPDATE containers "
                    "SET resources = COALESCE(resources, '{}') || "
                    "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                    "WHERE id = :cid"
                ),
                {"cid": cid, "url": host_shim_url},
            )
            # Update the row copy so the readiness poll uses the new URL.
            row = dict(row)
            row["resources"] = {"_host_shim_url": host_shim_url}
        await _poll_readyz(
            cid,
            timeout_s=READYZ_TIMEOUT,
            row=row,
            shim_port=getattr(settings, "shim_port", 8080),
        )
        await transition(db, cid, "provisioning", "running")
        await _set(db, cid, last_active_at="now()")


async def recover(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    settings: Any = None,
) -> None:
    """Recovery routine (spec §4.12).

    CAS into recovering from {running, recovering}; bounded backed-off restart;
    falls through to error on exhaustion.
    """
    async with container_lock(cid):
        # Determine starting state so we can choose the right CAS entry point.
        # error → provisioning → running  (API-triggered recover from error state; spec §4.12)
        # running / recovering → recovering → running/error  (reconciler-triggered path)
        starting_status = await current_status(db, cid)

        if starting_status == "error":
            # API-triggered recovery: error → provisioning first, then restart.
            if not await transition(db, cid, "error", "provisioning"):
                return  # Already moved by another actor.
            intermediate = "provisioning"
            terminal_ok = "running"
            terminal_fail = "error"
        else:
            # Reconciler path: running/recovering → recovering.
            if not await transition_from_any(db, cid, {"running", "recovering"}, "recovering"):
                return  # Someone else owns it or already in error.
            intermediate = "recovering"
            terminal_ok = "running"
            terminal_fail = "error"

        last_err: Exception | None = None
        for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
            await _set(db, cid, recovery_attempts=attempt)
            try:
                try:
                    await shim.post(cid, "/shutdown", best_effort=True)
                except Exception:  # noqa: BLE001
                    pass
                row = await _load(db, cid)
                await docker_ctl.stop(
                    docker_client, row["docker_name"], STOP_GRACE_SECONDS
                )
                if not await docker_ctl.exists(docker_client, row["docker_name"]):
                    host_shim_url = await docker_ctl.run_from_volume(
                        docker_client,
                        row,
                        settings=settings,
                        network=getattr(settings, "internal_network", None),
                        shim_port=getattr(settings, "shim_port", None),
                        bind_to_host=getattr(settings, "bind_shim_port_to_host", False),
                        extra_env=getattr(settings, "agent_extra_env", None),
                    )
                    if host_shim_url is not None:
                        await db.execute(
                            text(
                                "UPDATE containers "
                                "SET resources = COALESCE(resources, '{}') || "
                                "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                                "WHERE id = :cid"
                            ),
                            {"cid": cid, "url": host_shim_url},
                        )
                        row = dict(row)
                        row["resources"] = {"_host_shim_url": host_shim_url}
                else:
                    await docker_ctl.start(docker_client, row["docker_name"])
                    # Docker re-assigns ephemeral host ports on every restart
                    # (when the container was provisioned with bind_to_host=True).
                    # Reload and persist the new binding so _poll_readyz and
                    # subsequent shim calls use the correct host URL.
                    _shim_port = getattr(settings, "shim_port", 8080)
                    new_host_url = await docker_ctl.get_host_shim_url(
                        docker_client, row["docker_name"], _shim_port
                    )
                    if new_host_url is not None:
                        await db.execute(
                            text(
                                "UPDATE containers "
                                "SET resources = COALESCE(resources, '{}') || "
                                "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                                "WHERE id = :cid"
                            ),
                            {"cid": cid, "url": new_host_url},
                        )
                        row = dict(row)
                        row["resources"] = {"_host_shim_url": new_host_url}
                await _poll_readyz(
                    cid,
                    timeout_s=READYZ_TIMEOUT,
                    row=row,
                    shim_port=getattr(settings, "shim_port", 8080),
                )
                # Recovery succeeded — audit then transition.
                await audit(
                    db,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action="container.recover",
                    target_type="container",
                    target_id=cid,
                    details={"attempt": attempt},
                )
                await transition(db, cid, intermediate, terminal_ok)
                await _set(db, cid, recovery_attempts=0, error_message=None, last_active_at="now()")
                return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < MAX_RECOVERY_ATTEMPTS:
                    await asyncio.sleep(RECOVERY_BACKOFF[attempt - 1])

        # All attempts exhausted.
        await transition(db, cid, intermediate, terminal_fail)
        await _set(
            db,
            cid,
            error_message=(
                f"recovery exhausted after {MAX_RECOVERY_ATTEMPTS} attempts: {last_err}"
            ),
        )
        await fail_tasks(db, cid, code="container_unrecoverable")


async def destroy(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> bool:
    """Recoverable teardown (spec §4.2): remove the Docker container, KEEP the
    workspace volume and the DB row -> 'archived'. The container rehydrates on the
    next task (bring_to_running) or via restore().

    Idempotent: returns False (no-op) if already archived/destroyed/deleting or if
    another actor owns the transition. The caller owns the transaction/commit.
    """
    async with container_lock(cid):
        if not await transition_from_any(db, cid, _ARCHIVING_SOURCES, "archiving"):
            return False  # already archived/terminal, or another actor owns it
        try:
            await shim.post(cid, "/shutdown", best_effort=True)
        except Exception:  # noqa: BLE001
            pass  # graceful best-effort; docker stop is the hard guarantee
        row = await _load(db, cid)
        await docker_ctl.stop(docker_client, row["docker_name"], STOP_GRACE_SECONDS)
        await docker_ctl.rm(docker_client, row["docker_name"])  # never touches the volume
        await transition(db, cid, "archiving", "archived")
        await _set(db, cid, archived_at="now()", error_message=None)
        await audit(
            db,
            actor_type=actor_type,
            actor_id=actor_id,
            action="container.destroy",
            target_type="container",
            target_id=cid,
        )
    return True


async def ensure_running_slot(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    tenant_id: str,
    *,
    limit: int,
) -> None:
    """Admission control (spec §4.13).

    If at max_running_containers, LRU-pause an idle live container to free a
    slot; if none can be freed (all busy) → 503 running_capacity_exhausted.
    """
    if await admission.live_count(db, tenant_id) < limit:
        return
    victim = await admission.lru_idle_running(db, tenant_id)
    if victim is None:
        raise APIError(
            503,
            "running_capacity_exhausted",
            "all live containers are busy; retry with backoff",
        )
    await pause(db, docker_client, shim, victim)  # victim is a different cid → safe lock


async def bring_to_running(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    tenant_id: str,
    *,
    limit: int,
    settings: Any = None,
) -> None:
    """Bring a container to running for a task (spec §4.6 / §4.10 / §4.13).

    Resume if paused, rehydrate if archived; otherwise require running.
    Admission control is applied before the transition.

    **Re-entrant lock note:** ``asyncio.Lock`` is NOT re-entrant.  This
    function holds the per-container lock, so it must NOT call
    ``resume()``/``rehydrate()`` (they re-acquire the same lock and would
    deadlock).  The resume/rehydrate bodies are inlined below.
    ``ensure_running_slot`` calls ``pause(victim)`` on a *different* cid,
    so its lock is a different object — safe.
    """
    async with container_lock(cid):
        status = await current_status(db, cid)
        if status == "running":
            return

        if status in ("paused", "archived"):
            await ensure_running_slot(db, docker_client, shim, tenant_id, limit=limit)

            if status == "paused":
                # Inline resume to avoid re-acquiring the same lock.
                if await transition(db, cid, "paused", "resuming"):
                    row = await _load(db, cid)  # Now includes resources column.
                    # The backing container may have been removed while paused
                    # (docker prune, host restart, reclaim). If it's gone,
                    # re-create it from its persistent volume rather than letting
                    # docker NotFound escape as a 500 — same recovery the archived
                    # and reconciler paths use.
                    if await docker_ctl.exists(docker_client, row["docker_name"]):
                        await docker_ctl.start(docker_client, row["docker_name"])
                    else:
                        await docker_ctl.run_from_volume(
                            docker_client,
                            row,
                            settings=settings,
                            network=getattr(settings, "internal_network", None),
                            shim_port=getattr(settings, "shim_port", None),
                            bind_to_host=getattr(
                                settings, "bind_shim_port_to_host", False
                            ),
                            extra_env=getattr(settings, "agent_extra_env", None),
                        )
                    # Docker re-assigns ephemeral host ports on every restart;
                    # update resources._host_shim_url so readyz + shim calls use
                    # the new binding.
                    _shim_port = getattr(settings, "shim_port", 8080)
                    new_host_url = await docker_ctl.get_host_shim_url(
                        docker_client, row["docker_name"], _shim_port
                    )
                    if new_host_url is not None:
                        await db.execute(
                            text(
                                "UPDATE containers "
                                "SET resources = COALESCE(resources, '{}') || "
                                "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                                "WHERE id = :cid"
                            ),
                            {"cid": cid, "url": new_host_url},
                        )
                        row = dict(row)
                        row["resources"] = {"_host_shim_url": new_host_url}
                    await _poll_readyz(
                        cid,
                        timeout_s=READYZ_TIMEOUT,
                        row=row,
                        shim_port=_shim_port,
                    )
                    await transition(db, cid, "resuming", "running")
                    await _set(db, cid, last_active_at="now()")
            else:  # archived
                # Inline rehydrate to avoid re-acquiring the same lock.
                if await transition(db, cid, "archived", "provisioning"):
                    row = await _load(db, cid)
                    host_shim_url = await docker_ctl.run_from_volume(
                        docker_client,
                        row,
                        settings=settings,
                        network=getattr(settings, "internal_network", None),
                        shim_port=getattr(settings, "shim_port", None),
                        bind_to_host=getattr(settings, "bind_shim_port_to_host", False),
                        extra_env=getattr(settings, "agent_extra_env", None),
                    )
                    if host_shim_url is not None:
                        await db.execute(
                            text(
                                "UPDATE containers "
                                "SET resources = COALESCE(resources, '{}') || "
                                "jsonb_build_object('_host_shim_url', CAST(:url AS text)) "
                                "WHERE id = :cid"
                            ),
                            {"cid": cid, "url": host_shim_url},
                        )
                        row = dict(row)
                        row["resources"] = {"_host_shim_url": host_shim_url}
                    await _poll_readyz(
                        cid,
                        timeout_s=READYZ_TIMEOUT,
                        row=row,
                        shim_port=getattr(settings, "shim_port", 8080),
                    )
                    await transition(db, cid, "provisioning", "running")
                    await _set(db, cid, last_active_at="now()")
            return

        raise APIError(409, "container_not_runnable", f"container is {status}")


async def restore(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    tenant_id: str,
    *,
    limit: int,
    settings: Any = None,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> None:
    """Bring a destroyed (archived) or paused container back to running on demand
    (spec §4.2). Reuses bring_to_running (admission control + rehydrate/resume).

    Only ``paused``/``archived`` containers are restorable; an already-``running``
    container is an idempotent no-op (no audit). Any other state (e.g. a
    reclaimed/terminal container) raises 409 via bring_to_running."""
    if await current_status(db, cid) == "running":
        return  # already running — nothing to restore, no audit
    await bring_to_running(
        db, docker_client, shim, cid, tenant_id, limit=limit, settings=settings
    )
    await audit(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="container.restore",
        target_type="container",
        target_id=cid,
    )


_UPDATABLE_STATES: set[str] = {"running", "paused", "archived", "error"}


async def update_image(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    tenant_id: str,
    image_tag: str,
    *,
    limit: int,
    settings: Any = None,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> None:
    """Move a container onto ``image_tag`` (any tag, incl. downgrade).

    Pulls/validates the target image FIRST; only then persists the tag and, for
    live containers, destroys + restores from the retained volume so it comes back
    on the new image. ``archived`` containers only have their tag updated — the new
    image applies on the next restore. The caller commits the session.

    Drift-window note: ``image_tag`` is written by ``_set`` and committed only
    after ``restore`` succeeds (the caller owns the transaction). If ``restore``
    fails mid-update the transaction rolls back the tag change while ``destroy``
    has already removed the old container — the container is left in the
    ``archived`` state with the *previously-committed* tag. The reconciler /
    rehydrate path will bring it back on that prior tag. This is a known,
    reconciler-mitigated limitation (documented fast-follow), not fixed here.
    """
    # Deferred import avoids any import cycle with docker_ctl.provision.
    from control_plane.docker_ctl import provision

    status = await current_status(db, cid)
    if status not in _UPDATABLE_STATES:
        raise api_error(
            409,
            "container_not_updatable",
            f"cannot update image while container is {status}",
        )

    try:
        await asyncio.to_thread(
            provision.pull_or_verify_image, docker_client, settings, image_tag
        )
    except provision.ImageUnavailable as e:
        raise api_error(422, "image_unavailable", str(e)) from e

    await _set(db, cid, image_tag=image_tag)

    # Audit the image update in both branches (active recreate and archived tag-only).
    await audit(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="container.update_image",
        target_type="container",
        target_id=cid,
        details={"image_tag": image_tag},
    )

    if status in {"running", "paused", "error"}:
        await destroy(db, docker_client, shim, cid, actor_type=actor_type, actor_id=actor_id)
        await restore(
            db,
            docker_client,
            shim,
            cid,
            tenant_id,
            limit=limit,
            settings=settings,
            actor_type=actor_type,
            actor_id=actor_id,
        )


async def delete(
    db: _Executable,
    docker_client: Any,
    shim: Any,
    cid: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> bool:
    """Permanent purge (spec §4.2): remove the Docker container + volume + the DB
    row (tasks cascade to events). audit_log is FK-free and retained.

    Routes through a transient 'deleting' status BEFORE the irreversible teardown
    so an interrupted delete is finished by the reconciler's FINISH_DELETE.
    Returns True if this call performed the delete, False if the row was already
    gone / owned by another actor. The caller owns the transaction/commit.
    """
    async with container_lock(cid):
        if await current_status(db, cid) is None:
            return False  # already deleted
        if not await transition_from_any(
            db, cid, _NON_TERMINAL | {"destroying", "destroyed"}, "deleting"
        ):
            return False
        try:
            await shim.post(cid, "/shutdown", best_effort=True)
        except Exception:  # noqa: BLE001
            pass
        row = await _load(db, cid)
        await docker_ctl.stop(docker_client, row["docker_name"], STOP_GRACE_SECONDS)
        await docker_ctl.rm(docker_client, row["docker_name"])
        await docker_ctl.volume_rm(docker_client, row["volume_name"])
        # Purge dependent rows, then the container row, in the caller's transaction.
        await db.execute(text("DELETE FROM tasks WHERE container_id = :cid"), {"cid": cid})
        await audit(
            db,
            actor_type=actor_type,
            actor_id=actor_id,
            action="container.delete",
            target_type="container",
            target_id=cid,
        )
        await db.execute(text("DELETE FROM containers WHERE id = :cid"), {"cid": cid})
    return True


async def fail_tasks(db: _Executable, cid: str, *, code: str) -> None:
    """Mark every pending/running task on the container failed (spec §4.11/§4.12)."""
    await db.execute(
        text(
            "UPDATE tasks SET status='failed', error_code=:code, ended_at=now() "
            "WHERE container_id = :cid AND status IN ('pending','running')"
        ),
        {"cid": cid, "code": code},
    )

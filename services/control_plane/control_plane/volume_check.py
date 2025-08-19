"""Workspace volume-size check job (spec §8.4).

Spec §8.4 caps each workspace at 10 GiB.  Plain Docker named volumes have no
hard size cap, so this module implements the daily fallback check: measure each
non-destroyed container's workspace volume and, when it exceeds the tenant's
max_workspace_volume_size_mb (default 10240, spec §4.4/§8.4), emit a structured
warn log and an append-only audit_log row (action="volume.over_limit").

Alerting only — never deletes data (spec §8.4).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from control_plane.audit import audit
from control_plane.lifecycle import _Executable as _DB

log = logging.getLogger("volume_check")

MeasureFn = Callable[[object, str], Awaitable[int]]


def over_limit_mb(used_mb: int, limit_mb: int) -> bool:
    """At-or-below the cap is fine; only strictly over triggers an alert (spec §8.4)."""
    return used_mb > limit_mb


async def _measure_volume_mb(client: object, volume_name: str) -> int:
    """Measure a named volume's size in MB by mounting it read-only in a throwaway
    busybox container and running `du -sm`. Works whether or not the owning agent
    container is running (it's a separate mount)."""

    def _run() -> int:
        out = client.containers.run(  # type: ignore[attr-defined]
            image="busybox:1.36",
            command=["sh", "-c", "du -sm /v | cut -f1"],
            volumes={volume_name: {"bind": "/v", "mode": "ro"}},
            remove=True,
            network_mode="none",
        )
        return int(out.decode().strip().splitlines()[-1])

    return await asyncio.to_thread(_run)


async def _candidates(db: _DB) -> list[tuple[str, str, int]]:
    """(container_id, volume_name, limit_mb) for every non-destroyed container,
    with the tenant's max_workspace_volume_size_mb (default 10240 = 10 GiB, §8.4)."""
    res = await db.execute(
        text(
            "SELECT c.id, c.volume_name, "
            "COALESCE((t.limits->>'max_workspace_volume_size_mb')::int, 10240) "
            "FROM containers c JOIN tenants t ON t.id = c.tenant_id "
            "WHERE c.status <> 'destroyed'"
        )
    )
    return [(r[0], r[1], r[2]) for r in res.fetchall()]


async def volume_size_sweep(
    db: _DB,
    docker_client: object,
    shim: object = None,
    *,
    measure: MeasureFn = _measure_volume_mb,
) -> int:
    """Measure each workspace volume; alert (log + audit_log) on those over the cap.

    Returns the number of over-limit volumes found. Never deletes data (§8.4).
    """
    alerts = 0
    for cid, volume_name, limit_mb in await _candidates(db):
        try:
            used_mb = await measure(docker_client, volume_name)
        except Exception:  # noqa: BLE001
            log.exception("volume measure failed for %s (%s)", cid, volume_name)
            continue
        if over_limit_mb(used_mb, limit_mb):
            alerts += 1
            log.warning(
                "workspace volume over limit",
                extra={
                    "container_id": cid,
                    "volume": volume_name,
                    "used_mb": used_mb,
                    "limit_mb": limit_mb,
                },
            )
            await audit(
                db,
                actor_type="system",
                action="volume.over_limit",
                target_type="container",
                target_id=cid,
                details={"used_mb": used_mb, "limit_mb": limit_mb},
            )
    return alerts

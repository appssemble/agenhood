from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import text

# spec §4.4/§4.13: live = running + inbound transients (provisioning, resuming).
# Pausing/archiving/destroying are *leaving* states — not counted toward the live cap.
LIVE_STATES = ("running", "provisioning", "resuming")


# ---- DB protocol (matches AsyncSession.execute signature) ----------------------
class _Executable(Protocol):
    async def execute(
        self, statement: Any, params: Any = None
    ) -> Any: ...  # noqa: E704


# ---- admission queries (spec §4.13) -------------------------------------------

async def live_count(
    db: _Executable,
    tenant_id: str,
    exclude: str | None = None,
) -> int:
    """Number of live containers for *tenant_id*.

    Live means status ∈ {running, provisioning, resuming}.  Pass *exclude* to
    omit one container id from the count (e.g. when evaluating whether to
    create a replacement before destroying the candidate).
    """
    if exclude is None:
        res = await db.execute(
            text(
                "SELECT count(*) FROM containers "
                "WHERE tenant_id = :tid AND status = ANY(:live_states)"
            ),
            {"tid": tenant_id, "live_states": list(LIVE_STATES)},
        )
    else:
        res = await db.execute(
            text(
                "SELECT count(*) FROM containers "
                "WHERE tenant_id = :tid AND status = ANY(:live_states) AND id <> :exclude"
            ),
            {"tid": tenant_id, "live_states": list(LIVE_STATES), "exclude": exclude},
        )
    return int(res.scalar() or 0)


async def active_task_count(db: _Executable, cid: str) -> int:
    """Number of pending-or-running tasks assigned to container *cid*."""
    res = await db.execute(
        text(
            "SELECT count(*) FROM tasks "
            "WHERE container_id = :cid AND status IN ('pending','running')"
        ),
        {"cid": cid},
    )
    return int(res.scalar() or 0)


async def lru_idle_running(db: _Executable, tenant_id: str) -> str | None:
    """Least-recently-used idle live container for *tenant_id*.

    Selects the container with:
    - status = 'running'
    - zero in-flight tasks (no pending/running tasks)
    - oldest last_task_at (NULLS FIRST so never-used containers evict first)

    Returns the container id, or None if all running containers are busy.
    Never returns a busy container (spec §4.13).
    """
    res = await db.execute(
        text(
            "SELECT c.id FROM containers c "
            "WHERE c.tenant_id = :tid AND c.status = 'running' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM tasks t "
            "  WHERE t.container_id = c.id AND t.status IN ('pending','running')"
            ") "
            "ORDER BY c.last_task_at ASC NULLS FIRST "
            "LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = res.first()
    return str(row[0]) if row else None

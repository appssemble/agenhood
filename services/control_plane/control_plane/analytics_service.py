"""Pure SQL aggregation over the tasks table. Importable for unit tests.

All queries are tenant-scoped and key on tasks.created_at in UTC. `interval`
and `by` are validated against fixed whitelists by callers/routers; the values
that reach SQL identifiers here come only from those whitelists.

Note: `trunc` (the date_trunc unit) and `step` (the generate_series interval)
are interpolated directly into the SQL because asyncpg's prepared-statement type
inference cannot bind them as parameters when Postgres expects them as literal
text/interval values. Both values come exclusively from hardcoded whitelists so
there is no SQL-injection risk.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, bindparam, text

from control_plane.schemas import BreakdownGroupOut, UsageBucketOut

_INTERVAL_STEP = {"hour": "1 hour", "day": "1 day"}


def _usage_sql(trunc: str, step: str) -> Any:
    """Build the usage series SQL with whitelisted literals interpolated.

    The :start and :end params are given explicit TIMESTAMP(timezone=True) types
    so asyncpg can resolve the date_trunc overload without ambiguity.
    """
    return text(
        f"""
        SELECT b.bucket AS start,
               COALESCE(SUM(t.tokens_in), 0)       AS tokens_in,
               COALESCE(SUM(t.tokens_out), 0)      AS tokens_out,
               COUNT(t.id)                         AS tasks,
               COALESCE(SUM(t.iterations_used), 0) AS iterations
        FROM generate_series(
               date_trunc('{trunc}', :start),
               date_trunc('{trunc}', :end - interval '1 microsecond'),
               interval '{step}'
             ) AS b(bucket)
        LEFT JOIN tasks t
               ON t.tenant_id = :tenant_id
              AND t.created_at >= :start
              AND t.created_at <  :end
              AND date_trunc('{trunc}', t.created_at) = b.bucket
        GROUP BY b.bucket
        ORDER BY b.bucket
        """
    ).bindparams(
        bindparam("start", type_=TIMESTAMP(timezone=True)),
        bindparam("end", type_=TIMESTAMP(timezone=True)),
    )


async def usage_series(
    session: Any, *, tenant_id: str, start: datetime, end: datetime, interval: str
) -> list[UsageBucketOut]:
    step = _INTERVAL_STEP[interval]
    rows = (
        await session.execute(
            _usage_sql(interval, step),
            {"tenant_id": tenant_id, "start": start, "end": end},
        )
    ).all()
    return [
        UsageBucketOut(
            start=r.start.isoformat(),
            tokens_in=int(r.tokens_in), tokens_out=int(r.tokens_out),
            tasks=int(r.tasks), iterations=int(r.iterations),
        )
        for r in rows
    ]


_BREAKDOWN_COL = {
    "container": "t.container_id",
    "driver": "t.driver",
    "model": "t.model",
    "status": "t.status",
}

_AGG = (
    "COALESCE(SUM(t.tokens_in),0)  AS tokens_in, "
    "COALESCE(SUM(t.tokens_out),0) AS tokens_out, "
    "COUNT(t.id)                   AS tasks, "
    "COALESCE(SUM(t.iterations_used),0) AS iterations"
)


async def breakdown(
    session: Any, *, tenant_id: str, start: datetime, end: datetime, by: str
) -> list[BreakdownGroupOut]:
    col = _BREAKDOWN_COL[by]  # whitelisted identifier — safe to interpolate
    where = ("WHERE t.tenant_id = :tenant_id "
             "AND t.created_at >= :start AND t.created_at < :end")
    if by == "container":
        sql = text(
            f"SELECT t.container_id AS key, c.name AS label, {_AGG} "
            f"FROM tasks t JOIN containers c ON c.id = t.container_id AND c.tenant_id = t.tenant_id "
            f"{where} GROUP BY t.container_id, c.name"
        )
    else:
        sql = text(
            f"SELECT {col} AS key, {_AGG} "
            f"FROM tasks t {where} GROUP BY {col}"
        )
    rows = (
        await session.execute(
            sql, {"tenant_id": tenant_id, "start": start, "end": end}
        )
    ).all()
    out: list[BreakdownGroupOut] = []
    for r in rows:
        key = "" if r.key is None else str(r.key)
        label = str(getattr(r, "label", None) or key) if by == "container" else (key or "(none)")
        out.append(BreakdownGroupOut(
            key=key, label=label,
            tokens_in=int(r.tokens_in), tokens_out=int(r.tokens_out),
            tasks=int(r.tasks), iterations=int(r.iterations),
        ))
    return out

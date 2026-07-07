from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import analytics_service
from control_plane.auth import Principal
from control_plane.errors import validation_error
from control_plane.routers.containers import _principal, _session, _tid
from control_plane.schemas import BreakdownResponse, UsageResponse

router = APIRouter(tags=["Analytics"])

_INTERVALS = {"hour", "day"}
_BY = {"container", "driver", "model", "status"}


def _parse_dt(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise validation_error(f"invalid {field}: not ISO-8601", field=field) from None
    if dt.tzinfo is None:
        raise validation_error(f"{field} must include a timezone offset", field=field)
    return dt


def _range(from_: str, to: str | None) -> tuple[datetime, datetime]:
    start = _parse_dt(from_, "from")
    end = _parse_dt(to, "to") if to else datetime.now(UTC)
    if end <= start:
        raise validation_error("'to' must be after 'from'", field="to")
    return start, end


@router.get(
    "/analytics/usage",
    response_model=UsageResponse,
    response_description="Token/task usage bucketed over the requested time range.",
)
async def get_usage(
    from_: Annotated[
        str,
        Query(
            alias="from",
            description="ISO-8601 start of the range; must include a timezone offset.",
        ),
    ],
    interval: Annotated[
        str, Query(description="Bucket granularity; must be `hour` or `day`.")
    ],
    to: Annotated[
        str | None,
        Query(
            description=(
                "ISO-8601 end of the range (must include a timezone offset); "
                "defaults to now (UTC)."
            ),
        ),
    ] = None,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Return time-bucketed usage for the caller's tenant.

    Aggregates token and task counts into `hour` or `day` buckets over the
    `[from, to)` range (defaulting `to` to now in UTC). Serialized with the
    range start under the `from` key.

    Requires a tenant-scoped bearer credential (staff credentials with
    tenant_id=None are rejected with 403).

    Errors: 400 (validation_error) when `interval` is not `hour`/`day`, when
    `from`/`to` are not ISO-8601 or lack a timezone offset, or when `to` is not
    after `from`; 403 when the credential is not tenant-scoped.
    """
    tid = _tid(principal)
    if interval not in _INTERVALS:
        raise validation_error("interval must be 'hour' or 'day'", field="interval")
    start, end = _range(from_, to)
    series = await analytics_service.usage_series(
        session, tenant_id=tid, start=start, end=end, interval=interval
    )
    return UsageResponse(
        from_=start.isoformat(), to=end.isoformat(), interval=interval, series=series
    ).model_dump(by_alias=True)


@router.get(
    "/analytics/breakdown",
    response_model=BreakdownResponse,
    response_description="Usage totals grouped by the requested dimension over the time range.",
)
async def get_breakdown(
    from_: Annotated[
        str,
        Query(
            alias="from",
            description="ISO-8601 start of the range; must include a timezone offset.",
        ),
    ],
    by: Annotated[
        str,
        Query(
            description=(
                "Grouping dimension; one of `container`, `driver`, `model`, or `status`."
            ),
        ),
    ],
    to: Annotated[
        str | None,
        Query(
            description=(
                "ISO-8601 end of the range (must include a timezone offset); "
                "defaults to now (UTC)."
            ),
        ),
    ] = None,
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Return usage grouped by a dimension for the caller's tenant.

    Aggregates token and task usage over the `[from, to)` range (defaulting
    `to` to now in UTC), grouped by `by` (`container`, `driver`, `model`, or
    `status`). Serialized with the range start under the `from` key.

    Requires a tenant-scoped bearer credential (staff credentials with
    tenant_id=None are rejected with 403).

    Errors: 400 (validation_error) when `by` is not one of the allowed
    dimensions, when `from`/`to` are not ISO-8601 or lack a timezone offset, or
    when `to` is not after `from`; 403 when the credential is not tenant-scoped.
    """
    tid = _tid(principal)
    if by not in _BY:
        raise validation_error("by must be one of container|driver|model|status", field="by")
    start, end = _range(from_, to)
    groups = await analytics_service.breakdown(
        session, tenant_id=tid, start=start, end=end, by=by
    )
    return BreakdownResponse(
        from_=start.isoformat(), to=end.isoformat(), by=by, groups=groups
    ).model_dump(by_alias=True)

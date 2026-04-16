from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import analytics_service
from control_plane.auth import Principal
from control_plane.errors import validation_error
from control_plane.routers.containers import _principal, _session, _tid
from control_plane.schemas import BreakdownResponse, UsageResponse

router = APIRouter()

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


@router.get("/analytics/usage")
async def get_usage(
    from_: str = Query(..., alias="from"),
    to: str | None = Query(None),
    interval: str = Query(...),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
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


@router.get("/analytics/breakdown")
async def get_breakdown(
    from_: str = Query(..., alias="from"),
    to: str | None = Query(None),
    by: str = Query(...),
    principal: Principal = Depends(_principal),
    session: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
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

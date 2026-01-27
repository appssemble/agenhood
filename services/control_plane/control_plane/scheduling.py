"""Pure schedule validation + next-run computation for scheduled tasks.

No DB or I/O — everything here is a deterministic function of (schedule, tz, now)
so it can be unit-tested exhaustively, including DST boundaries.

schedule shapes (presets only in v1):
    {"kind": "once"}                                            # fires from stored next_run_at
    {"kind": "recurring", "unit": "hour"}
    {"kind": "recurring", "unit": "day",   "time": "HH:MM"}
    {"kind": "recurring", "unit": "week",  "time": "HH:MM", "weekdays": [1..7]}   # ISO, 1=Mon
    {"kind": "recurring", "unit": "month", "time": "HH:MM", "day_of_month": 1..31}
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UTC = ZoneInfo("UTC")
_VALID_UNITS = {"hour", "day", "week", "month"}


def _parse_hhmm(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or ":" not in value:
        raise ValueError("time must be 'HH:MM'")
    hh, _, mm = value.partition(":")
    try:
        hour, minute = int(hh), int(mm)
    except ValueError as exc:
        raise ValueError("time must be 'HH:MM'") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time out of range")
    return hour, minute


def validate_schedule(schedule: dict, timezone: str) -> None:
    """Raise ValueError if the schedule or timezone is malformed."""
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError(f"invalid timezone: {timezone}") from exc

    kind = schedule.get("kind")
    if kind not in ("once", "recurring"):
        raise ValueError("schedule.kind must be 'once' or 'recurring'")
    if kind == "once":
        return

    unit = schedule.get("unit")
    if unit not in _VALID_UNITS:
        raise ValueError("schedule.unit must be one of hour|day|week|month")
    if unit != "hour":
        _parse_hhmm(schedule.get("time"))
    if unit == "week":
        weekdays = schedule.get("weekdays")
        if (
            not isinstance(weekdays, list)
            or not weekdays
            or not all(isinstance(d, int) and 1 <= d <= 7 for d in weekdays)
        ):
            raise ValueError("weekly schedule requires weekdays as a non-empty list of 1..7")
    if unit == "month":
        dom = schedule.get("day_of_month")
        if not isinstance(dom, int) or not (1 <= dom <= 31):
            raise ValueError("monthly schedule requires day_of_month in 1..31")


def _month_candidate(local: datetime, dom: int, hour: int, minute: int) -> datetime:
    last = calendar.monthrange(local.year, local.month)[1]
    return local.replace(
        day=min(dom, last), hour=hour, minute=minute, second=0, microsecond=0
    )


def compute_next_run(schedule: dict, timezone: str, after: datetime) -> datetime | None:
    """Next fire time (tz-aware UTC) strictly after `after`, or None for 'once'.

    `after` must be tz-aware. 'once' schedules are never recomputed here — their
    fire time lives in the stored next_run_at column.
    """
    if schedule.get("kind") == "once":
        return None

    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")

    tz = ZoneInfo(timezone)
    local = after.astimezone(tz)
    unit = schedule["unit"]

    if unit == "hour":
        nxt = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return nxt.astimezone(_UTC)

    hour, minute = _parse_hhmm(schedule["time"])

    if unit == "day":
        cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= local:
            cand += timedelta(days=1)
        return cand.astimezone(_UTC)

    if unit == "week":
        weekdays = sorted(set(schedule["weekdays"]))
        for delta in range(0, 8):
            cand = (local + timedelta(days=delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if cand > local and cand.isoweekday() in weekdays:
                return cand.astimezone(_UTC)
        return None  # unreachable for a validated weekly schedule

    # unit == "month"
    dom = schedule["day_of_month"]
    cand = _month_candidate(local, dom, hour, minute)
    if cand <= local:
        year = local.year + (1 if local.month == 12 else 0)
        month = 1 if local.month == 12 else local.month + 1
        cand = _month_candidate(local.replace(year=year, month=month, day=1), dom, hour, minute)
    return cand.astimezone(_UTC)

"""Pure unit tests for schedule validation + next-run computation."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane.scheduling import compute_next_run, validate_schedule

pytestmark = pytest.mark.unit


def _utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_validate_rejects_bad_timezone():
    with pytest.raises(ValueError):
        validate_schedule({"kind": "once"}, "Not/AZone")


def test_validate_rejects_bad_kind():
    with pytest.raises(ValueError):
        validate_schedule({"kind": "nope"}, "UTC")


def test_validate_weekly_requires_weekdays():
    with pytest.raises(ValueError):
        validate_schedule({"kind": "recurring", "unit": "week", "time": "09:00"}, "UTC")


def test_validate_monthly_requires_day_of_month():
    with pytest.raises(ValueError):
        validate_schedule({"kind": "recurring", "unit": "month", "time": "09:00"}, "UTC")


def test_validate_accepts_valid_daily():
    validate_schedule({"kind": "recurring", "unit": "day", "time": "09:00"}, "Europe/Bucharest")


def test_once_never_recomputes():
    assert compute_next_run({"kind": "once"}, "UTC", _utc(2026, 6, 17, 8, 0)) is None


def test_daily_same_day_when_time_ahead():
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "day", "time": "09:00"}, "UTC", _utc(2026, 6, 17, 8, 0)
    )
    assert nxt == _utc(2026, 6, 17, 9, 0)


def test_daily_next_day_when_time_passed():
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "day", "time": "09:00"}, "UTC", _utc(2026, 6, 17, 9, 0)
    )
    assert nxt == _utc(2026, 6, 18, 9, 0)


def test_daily_honors_timezone():
    # 09:00 Europe/Bucharest in summer is UTC+3 -> 06:00 UTC.
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "day", "time": "09:00"},
        "Europe/Bucharest",
        _utc(2026, 6, 17, 4, 0),
    )
    assert nxt == _utc(2026, 6, 17, 6, 0)


def test_hourly_advances_to_next_top_of_hour():
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "hour"}, "UTC", _utc(2026, 6, 17, 8, 30)
    )
    assert nxt == _utc(2026, 6, 17, 9, 0)


def test_weekly_picks_next_listed_weekday():
    # 2026-06-17 is a Wednesday (isoweekday 3). Ask for Mon(1)+Fri(5) at 09:00 UTC.
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "week", "time": "09:00", "weekdays": [1, 5]},
        "UTC",
        _utc(2026, 6, 17, 10, 0),
    )
    # Next Friday is 2026-06-19.
    assert nxt == _utc(2026, 6, 19, 9, 0)


def test_monthly_clamps_to_month_length():
    # Ask for day 31 in a 30-day month context; February-style clamp.
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "month", "time": "09:00", "day_of_month": 31},
        "UTC",
        _utc(2026, 6, 17, 9, 0),
    )
    # June has 30 days -> clamps to 2026-06-30 09:00 (still ahead of the 17th).
    assert nxt == _utc(2026, 6, 30, 9, 0)


def test_monthly_rolls_to_next_month_when_passed():
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "month", "time": "09:00", "day_of_month": 1},
        "UTC",
        _utc(2026, 6, 17, 9, 0),
    )
    assert nxt == _utc(2026, 7, 1, 9, 0)


def test_monthly_rolls_december_to_january():
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "month", "time": "09:00", "day_of_month": 1},
        "UTC",
        _utc(2026, 12, 5, 9, 0),
    )
    assert nxt == _utc(2027, 1, 1, 9, 0)


def test_monthly_clamps_after_rollover_into_february():
    # Jan 31 already passed -> roll to February, clamp day 31 to Feb 28 (2027 not leap).
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "month", "time": "09:00", "day_of_month": 31},
        "UTC",
        _utc(2027, 1, 31, 10, 0),
    )
    assert nxt == _utc(2027, 2, 28, 9, 0)


def test_weekly_same_day_before_time():
    # 2026-06-17 is Wednesday (isoweekday 3). At 08:00, a Wed schedule at 09:00 fires today.
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "week", "time": "09:00", "weekdays": [3]},
        "UTC",
        _utc(2026, 6, 17, 8, 0),
    )
    assert nxt == _utc(2026, 6, 17, 9, 0)


def test_daily_preserves_wall_clock_across_spring_forward():
    # Europe/Bucharest spring-forward 2026: clocks jump 03:00->04:00 on Sun 2026-03-29.
    # A daily 09:00 local schedule must still land at 09:00 local (06:00 UTC) the next day.
    nxt = compute_next_run(
        {"kind": "recurring", "unit": "day", "time": "09:00"},
        "Europe/Bucharest",
        _utc(2026, 3, 28, 10, 0),  # 12:00 local on the 28th
    )
    # Next 09:00 local on 2026-03-29 is 06:00 UTC (already on summer time, UTC+3).
    assert nxt == _utc(2026, 3, 29, 6, 0)


def test_compute_next_run_rejects_naive_after():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        compute_next_run(
            {"kind": "recurring", "unit": "day", "time": "09:00"},
            "UTC",
            datetime(2026, 6, 17, 8, 0),  # naive
        )

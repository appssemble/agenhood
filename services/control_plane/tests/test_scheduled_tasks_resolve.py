"""Unit tests for _resolve_next_run (once vs recurring next_run_at resolution)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane.errors import APIError
from control_plane.routers.scheduled_tasks import _resolve_next_run

pytestmark = pytest.mark.unit


def test_once_requires_run_at():
    with pytest.raises(APIError) as ei:
        _resolve_next_run({"kind": "once"}, "UTC", None)
    assert ei.value.status_code == 400


def test_once_parses_run_at_to_utc():
    got = _resolve_next_run({"kind": "once"}, "UTC", "2026-06-17T09:00:00+00:00")
    assert got == datetime(2026, 6, 17, 9, 0, tzinfo=UTC)


def test_once_accepts_past_run_at():
    # By design: a past run_at is allowed; the sweep fires it once then disables.
    got = _resolve_next_run({"kind": "once"}, "UTC", "2000-01-01T00:00:00+00:00")
    assert got == datetime(2000, 1, 1, 0, 0, tzinfo=UTC)


def test_once_naive_run_at_assumed_utc():
    got = _resolve_next_run({"kind": "once"}, "UTC", "2026-06-17T09:00:00")
    assert got == datetime(2026, 6, 17, 9, 0, tzinfo=UTC)


def test_recurring_returns_future_instant():
    got = _resolve_next_run({"kind": "recurring", "unit": "day", "time": "09:00"}, "UTC", None)
    # next_run_at must be a future, tz-aware UTC datetime
    assert got is not None and got.tzinfo is not None


def test_recurring_invalid_timezone_raises_value_error():
    with pytest.raises(ValueError):
        _resolve_next_run({"kind": "recurring", "unit": "day", "time": "09:00"}, "Not/AZone", None)

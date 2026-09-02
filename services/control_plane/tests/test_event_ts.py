"""The shim's own event timestamp must survive the trip into the DB.

Without it, `events.ts` falls back to its `server_default now()` — DB write
time. That reads as "close enough" for a task streamed live, but when the
control plane restarts mid-task the shim replays the whole backlog in one
burst, every row lands within milliseconds of its neighbours, and the stored
history claims the task took no time at all.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from control_plane.sse import event_ts

pytestmark = pytest.mark.unit


def test_uses_the_shim_timestamp():
    ts = event_ts({"seq": 1, "type": "log", "ts": "2026-09-02T10:00:00+00:00"})
    assert ts == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def test_accepts_a_z_suffix():
    ts = event_ts({"seq": 1, "type": "log", "ts": "2026-09-02T10:00:00Z"})
    assert ts == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def test_assumes_utc_when_the_timestamp_is_naive():
    ts = event_ts({"seq": 1, "type": "log", "ts": "2026-09-02T10:00:00"})
    assert ts == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize("bad", [{}, {"ts": None}, {"ts": "not-a-date"}, {"ts": 1234}])
def test_falls_back_to_now_rather_than_raising(bad):
    # Persistence is best-effort: a malformed frame must still be storable.
    before = datetime.now(UTC)
    ts = event_ts(bad)
    assert before - timedelta(seconds=5) <= ts <= datetime.now(UTC) + timedelta(seconds=5)
    assert ts.tzinfo is not None

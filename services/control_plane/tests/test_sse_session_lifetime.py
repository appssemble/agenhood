"""Unit test: _persist_event_best_effort must not hold more than one pooled
session at a time — i.e. each call opens and closes its own short-lived
session before returning.  This locks the "good half" of the SSE session
contract (per-event persistence already uses factory(), not Depends).

See incident: sse-db-pool-exhaustion-incident
"""
from __future__ import annotations

import pytest

import control_plane.routers.tasks as tasksmod

pytestmark = pytest.mark.unit


class _TrackingSession:
    def __init__(self, tracker):
        self._tracker = tracker

    async def __aenter__(self):
        self._tracker["open"] += 1
        self._tracker["max_open"] = max(self._tracker["max_open"], self._tracker["open"])
        return self

    async def __aexit__(self, *exc):
        self._tracker["open"] -= 1
        self._tracker["closed"] += 1
        return False

    async def execute(self, *a, **k):
        return None

    async def commit(self):
        self._tracker["commits"] += 1


@pytest.mark.asyncio
async def test_persist_event_uses_short_lived_session(monkeypatch):
    tracker = {"open": 0, "max_open": 0, "closed": 0, "commits": 0}

    def factory():
        return _TrackingSession(tracker)

    # Stub the row-apply helper so we test the session lifecycle, not the SQL.
    async def _noop_apply(s, task_id, event):
        return None

    monkeypatch.setattr(tasksmod, "_apply_event_to_task_row", _noop_apply, raising=False)

    # Persist a burst of events; each must open AND close its own session.
    for seq in range(1, 11):
        await tasksmod._persist_event_best_effort(
            factory, "tk_1", {"seq": seq, "type": "token_update", "payload": {}}
        )

    assert tracker["max_open"] == 1, "a stream must hold at most ONE pooled session at a time"
    assert tracker["closed"] == 10 and tracker["open"] == 0, "every session returned to the pool"

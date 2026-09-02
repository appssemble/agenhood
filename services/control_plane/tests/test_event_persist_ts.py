"""Persisted events carry the shim's timestamp, not the DB write time.

Reads the values back off the compiled statement, so no database is needed.
The postgresql dialect is required: the default dialect cannot compile the
JSONB payload column.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

import control_plane.routers.tasks as tasksmod

pytestmark = pytest.mark.unit


class _CapturingSession:
    """Records every statement executed, and compiles it on demand."""

    def __init__(self):
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return None

    async def commit(self):
        return None

    def params(self, index: int) -> dict:
        return self.statements[index].compile(dialect=pg_dialect()).params


@pytest.fixture
def session():
    return _CapturingSession()


@pytest.fixture
def factory(session):
    return lambda: session


async def test_insert_binds_the_shim_timestamp(factory, session, monkeypatch):
    async def _noop_apply(s, task_id, event):
        return None

    monkeypatch.setattr(tasksmod, "_apply_event_to_task_row", _noop_apply, raising=False)

    await tasksmod._persist_event_best_effort(
        factory,
        "tk_1",
        {"seq": 7, "type": "tool_call", "ts": "2026-09-02T10:00:00+00:00", "payload": {"name": "shell"}},
    )

    params = session.params(0)
    assert params["ts"] == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    assert params["seq"] == 7
    assert params["task_id"] == "tk_1"


async def test_insert_still_persists_an_event_with_a_broken_timestamp(factory, session, monkeypatch):
    async def _noop_apply(s, task_id, event):
        return None

    monkeypatch.setattr(tasksmod, "_apply_event_to_task_row", _noop_apply, raising=False)

    await tasksmod._persist_event_best_effort(
        factory, "tk_1", {"seq": 1, "type": "log", "ts": "garbage", "payload": {}}
    )

    params = session.params(0)
    assert params["seq"] == 1
    assert datetime.now(UTC) - params["ts"] < timedelta(seconds=5)


async def test_ended_at_comes_from_the_terminal_event(session):
    await tasksmod._apply_event_to_task_row(
        session,
        "tk_1",
        {
            "seq": 12,
            "type": "status_change",
            "ts": "2026-09-02T10:05:30+00:00",
            "payload": {"from": "running", "to": "completed", "result": {"output": "hi"}, "error": None},
        },
    )

    params = session.params(0)
    assert params["ended_at"] == datetime(2026, 9, 2, 10, 5, 30, tzinfo=UTC)
    assert params["status"] == "completed"

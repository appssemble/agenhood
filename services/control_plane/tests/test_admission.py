from __future__ import annotations

import datetime as _dt
from datetime import datetime, timedelta

import pytest

from control_plane import admission

pytestmark = pytest.mark.unit

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=_dt.UTC)


def _c(
    cid: str,
    status: str,
    last_task_at: datetime,
    in_flight: int,
) -> dict[str, object]:
    return {"id": cid, "status": status, "last_task_at": last_task_at, "in_flight": in_flight}


class _Res:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value

    def first(self) -> tuple[object] | None:
        if self._value is not None:
            return (self._value,)
        return None

    def fetchall(self) -> object:
        return self._value


class FakeDB:
    """Interprets the WHERE/ORDER intent of the three admission queries against in-memory rows."""

    def __init__(
        self,
        rows: list[dict[str, object]],
        task_counts: dict[str, int] | None = None,
    ) -> None:
        self.rows = rows
        self.task_counts: dict[str, int] = (
            task_counts
            if task_counts is not None
            else {str(c["id"]): int(c["in_flight"]) for c in rows}  # type: ignore[arg-type]
        )

    async def execute(
        self, stmt: object, params: object = None
    ) -> _Res:
        s = str(stmt).lower()
        p: dict[str, object] = params if isinstance(params, dict) else {}
        if "count(" in s and "containers" in s and "any(:live" in s.replace(" ", ""):
            live = {"running", "provisioning", "resuming"}
            exclude = p.get("exclude")
            n = sum(
                1
                for c in self.rows
                if c["status"] in live and c["id"] != exclude
            )
            return _Res(n)
        if "count(" in s and "containers" in s and "in (" in s:  # fallback live count form
            live = {"running", "provisioning", "resuming"}
            n = sum(1 for c in self.rows if c["status"] in live)
            return _Res(n)
        if "order by" in s and "last_task_at" in s:  # LRU candidate
            cands = [
                c
                for c in self.rows
                if c["status"] == "running"
                and self.task_counts.get(str(c["id"]), 0) == 0
            ]
            cands.sort(key=lambda c: c["last_task_at"])  # type: ignore[arg-type,return-value]
            return _Res(cands[0]["id"] if cands else None)
        if "tasks" in s and "count(" in s:  # active task count
            return _Res(self.task_counts.get(str(p.get("cid")), 0))
        raise AssertionError(f"unexpected query: {s}")


@pytest.mark.asyncio
async def test_live_count_counts_running_and_inbound_transients() -> None:
    rows = [
        _c("a", "running", NOW, 0),
        _c("b", "provisioning", NOW, 0),
        _c("c", "resuming", NOW, 0),
        _c("d", "paused", NOW, 0),        # not live
        _c("e", "archived", NOW, 0),      # not live
        _c("f", "pausing", NOW, 0),       # leaving, not counted toward live cap
    ]
    db = FakeDB(rows)
    assert await admission.live_count(db, "ten_x") == 3  # a, b, c


@pytest.mark.asyncio
async def test_lru_idle_picks_oldest_idle_running_never_busy() -> None:
    rows = [
        _c("busy_oldest", "running", NOW - timedelta(hours=5), 1),   # oldest but BUSY -> excluded
        _c("idle_old", "running", NOW - timedelta(hours=3), 0),       # the winner
        _c("idle_new", "running", NOW - timedelta(hours=1), 0),
        _c("paused", "paused", NOW - timedelta(hours=9), 0),          # not running -> excluded
    ]
    db = FakeDB(rows)
    victim = await admission.lru_idle_running(db, "ten_x")
    assert victim == "idle_old"


@pytest.mark.asyncio
async def test_lru_idle_returns_none_when_all_live_are_busy() -> None:
    rows = [
        _c("a", "running", NOW - timedelta(hours=2), 2),
        _c("b", "running", NOW - timedelta(hours=1), 1),
    ]
    db = FakeDB(rows)
    assert await admission.lru_idle_running(db, "ten_x") is None


@pytest.mark.asyncio
async def test_active_task_count_counts_pending_and_running() -> None:
    db = FakeDB([], task_counts={"con_z": 2})
    assert await admission.active_task_count(db, "con_z") == 2
    assert await admission.active_task_count(db, "con_absent") == 0

"""Unit tests for the idle-pause sweep (spec §4.8).

The sweep selects idle running containers (candidate query) and pauses each via
the guarded pause path. These tests cover the sweep orchestration and the shape
of the candidate query; the real SQL semantics are exercised against Postgres in
``test_idle_sweep_db.py``.
"""
from __future__ import annotations

import pytest

from control_plane import idle
from control_plane.errors import APIError

pytestmark = pytest.mark.unit


class _Res:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str]]:
        return self._rows


class _CandidateDB:
    """Returns a fixed candidate list and records SQL / commit / rollback calls."""

    def __init__(self, candidates: list[str]) -> None:
        self.candidates = candidates
        self.last_sql = ""
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt: object, params: object = None) -> _Res:
        self.last_sql = str(stmt)
        return _Res([(c,) for c in self.candidates])

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_idle_pause_sweep_pauses_each_candidate(monkeypatch) -> None:
    paused: list[str] = []

    async def fake_pause(db, dock, shim, cid, **kwargs):
        # Guarded pause must be called WITHOUT force so a container that became
        # busy between the candidate query and the pause is left alone (409).
        assert kwargs.get("force", False) is False
        paused.append(cid)

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    await idle.idle_pause_sweep(_CandidateDB(["con_1", "con_2"]), object(), shim=object())

    assert paused == ["con_1", "con_2"]


@pytest.mark.asyncio
async def test_idle_pause_sweep_skips_busy_race(monkeypatch) -> None:
    # A container that wins the submit/pause race raises 409 under the lock; the
    # sweep must skip it quietly and keep going.
    paused: list[str] = []

    async def fake_pause(db, dock, shim, cid, **kwargs):
        if cid == "busy":
            raise APIError(409, "container_not_runnable", "has in-flight tasks")
        paused.append(cid)

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    await idle.idle_pause_sweep(_CandidateDB(["busy", "con_ok"]), object(), shim=object())

    assert paused == ["con_ok"]


@pytest.mark.asyncio
async def test_idle_pause_sweep_continues_after_unexpected_error(monkeypatch) -> None:
    paused: list[str] = []

    async def fake_pause(db, dock, shim, cid, **kwargs):
        if cid == "boom":
            raise RuntimeError("docker exploded")
        paused.append(cid)

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    # Must not propagate; the remaining candidate is still paused.
    await idle.idle_pause_sweep(_CandidateDB(["boom", "con_ok"]), object(), shim=object())
    assert paused == ["con_ok"]


def _deadlock_error() -> Exception:
    """An exception shaped like a SQLAlchemy-wrapped asyncpg DeadlockDetectedError
    (sqlstate 40P01 on ``.orig``)."""

    class _Orig:
        sqlstate = "40P01"

    err = Exception("deadlock detected")
    err.orig = _Orig()  # type: ignore[attr-defined]
    return err


@pytest.mark.asyncio
async def test_idle_pause_sweep_retries_on_deadlock(monkeypatch) -> None:
    # Fix #3: a transient Postgres deadlock (40P01) on a candidate is retried once,
    # not logged-and-skipped. The poisoned transaction is rolled back first.
    attempts: dict[str, int] = {}
    paused: list[str] = []

    async def fake_pause(db, dock, shim, cid, **kwargs):
        attempts[cid] = attempts.get(cid, 0) + 1
        if attempts[cid] == 1:
            raise _deadlock_error()
        paused.append(cid)

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)
    db = _CandidateDB(["con_x"])
    await idle.idle_pause_sweep(db, object(), shim=object())

    assert attempts["con_x"] == 2  # retried after the deadlock
    assert paused == ["con_x"]
    assert db.rollbacks >= 1  # poisoned txn rolled back before retry


@pytest.mark.asyncio
async def test_idle_pause_sweep_retries_deadlock_only_once(monkeypatch) -> None:
    # A candidate that keeps deadlocking is given up after one retry; the sweep
    # continues to the next candidate.
    attempts: dict[str, int] = {}
    paused: list[str] = []

    async def fake_pause(db, dock, shim, cid, **kwargs):
        attempts[cid] = attempts.get(cid, 0) + 1
        if cid == "stuck":
            raise _deadlock_error()
        paused.append(cid)

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)
    await idle.idle_pause_sweep(_CandidateDB(["stuck", "con_ok"]), object(), shim=object())

    assert attempts["stuck"] == 2  # tried + one retry, then given up
    assert paused == ["con_ok"]  # sweep still pauses the next candidate


@pytest.mark.asyncio
async def test_idle_pause_sweep_does_not_retry_non_deadlock(monkeypatch) -> None:
    # A non-deadlock failure is logged and skipped without a retry.
    attempts: dict[str, int] = {}

    async def fake_pause(db, dock, shim, cid, **kwargs):
        attempts[cid] = attempts.get(cid, 0) + 1
        raise RuntimeError("boom")

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)
    await idle.idle_pause_sweep(_CandidateDB(["con_y", "con_z"]), object(), shim=object())

    assert attempts == {"con_y": 1, "con_z": 1}  # one attempt each, no retry


@pytest.mark.asyncio
async def test_idle_pause_sweep_commits_each_pause(monkeypatch) -> None:
    # Each successful pause must be committed. Without a commit the
    # running->pausing->paused UPDATEs roll back when the sweep's session closes,
    # so the container silently reverts to running and never appears paused.
    async def fake_pause(db, dock, shim, cid, **kwargs):
        return None

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    db = _CandidateDB(["con_1", "con_2"])
    await idle.idle_pause_sweep(db, object(), shim=object())

    assert db.commits == 2
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_idle_pause_sweep_rolls_back_busy_race(monkeypatch) -> None:
    # The 409 race must roll back its (read-only) transaction so the next
    # candidate runs on a clean session, and must not be committed.
    async def fake_pause(db, dock, shim, cid, **kwargs):
        if cid == "busy":
            raise APIError(409, "container_not_runnable", "has in-flight tasks")

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    db = _CandidateDB(["busy", "con_ok"])
    await idle.idle_pause_sweep(db, object(), shim=object())

    assert db.commits == 1     # only con_ok persisted
    assert db.rollbacks == 1   # busy's partial txn cleared


@pytest.mark.asyncio
async def test_idle_pause_sweep_rolls_back_on_error(monkeypatch) -> None:
    # An unexpected mid-pause failure must roll back so a poisoned transaction
    # does not cascade into the remaining candidates.
    async def fake_pause(db, dock, shim, cid, **kwargs):
        if cid == "boom":
            raise RuntimeError("docker exploded")

    monkeypatch.setattr(idle.lifecycle, "pause", fake_pause)

    db = _CandidateDB(["boom", "con_ok"])
    await idle.idle_pause_sweep(db, object(), shim=object())

    assert db.commits == 1
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_idle_candidates_query_shape() -> None:
    db = _CandidateDB(["con_1"])
    await idle._idle_candidates(db)
    sql = db.last_sql.lower()
    # Only running containers are candidates.
    assert "status = 'running'" in sql
    # Idle measured from the most recent of created/last_task/status_changed, so a
    # never-run or just-resumed container is not wrongly considered idle.
    assert "greatest(" in sql
    assert "created_at" in sql
    assert "last_task_at" in sql
    assert "status_changed_at" in sql
    # Per-tenant threshold.
    assert "idle_pause_minutes" in sql
    # In-flight tasks exclude a container from the candidate set.
    assert "not exists" in sql
    assert "pending" in sql and "running" in sql


@pytest.mark.asyncio
async def test_lifespan_registers_idle_pause_sweep(monkeypatch) -> None:
    # The sweep is useless unless it is launched: assert _lifespan wires an
    # "idle-pause-sweep" background task alongside the other sweeps.
    import control_plane.app as appmod
    from control_plane.config import Settings

    monkeypatch.setattr(appmod.docker, "from_env", lambda: object())

    async def _noop_reconcile(*a, **k):
        return None

    monkeypatch.setattr(appmod, "reconcile_all", _noop_reconcile)

    app = appmod.create_app(Settings.from_env())
    async with appmod._lifespan(app):
        names = {t.get_name() for t in app.state.bg_tasks}

    assert "idle-pause-sweep" in names

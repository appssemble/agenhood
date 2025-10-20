"""Unit tests for the high-level lifecycle ops (Task 5).

All ops are tested against a fake DB and fake docker/shim clients so no real
docker daemon or Postgres is required.  The fake DB interprets the SQL
produced by lifecycle.py's inner helpers (transition, _load, _set, admission
queries) via lightweight string matching.
"""
from __future__ import annotations

import pytest

from control_plane import lifecycle
from control_plane.errors import APIError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeShim:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def post(self, cid: str, path: str, **kw: object) -> dict[str, object]:
        self.calls.append((cid, path))
        return {"ok": True}

    async def cancel_all(self, cid: str) -> None:
        self.calls.append((cid, "cancel_all"))


class FakeDocker:
    """Records lifecycle calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []


class StatusDB:
    """Minimal stand-in for an AsyncSession.

    Interprets the SQL strings emitted by lifecycle.py helpers:
    - UPDATE containers ... SET status = :new WHERE ... AND status = :expected  (CAS)
    - SELECT status FROM containers WHERE id = :cid                             (current_status)
    - SELECT count(*) FROM tasks WHERE container_id = :cid ...                  (active_task_count)
    - SELECT count(*) FROM containers WHERE tenant_id ...                       (live_count)
    - SELECT ... FROM containers ORDER BY ...                                   (lru_idle_running)
    - SELECT id, tenant_id, docker_name, ... FROM containers WHERE id = :cid   (_load)
    - UPDATE containers SET <fields> WHERE id = :cid                            (_set)
    - UPDATE tasks SET status='failed' ...                                      (fail_tasks)
    - INSERT INTO audit_log ...                                                  (audit)
    """

    def __init__(
        self,
        status: str,
        active: int = 0,
        tenant: str = "ten_x",
        live: int = 0,
        docker_name: str = "agent-c-a",
        volume_name: str = "agent-vol-a",
    ) -> None:
        self.status = status
        self.active = active
        self.tenant = tenant
        self.live = live
        self.docker_name = docker_name
        self.volume_name = volume_name
        self.events: list[tuple[str, ...]] = []
        self.audit_rows: list[dict[str, object]] = []
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        self.events.append(("commit", self.status))

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append(("rollback", self.status))

    async def execute(self, stmt: object, params: object = None) -> _R:
        s = str(stmt).lower()
        p: dict[str, object] = params if isinstance(params, dict) else {}

        # CAS from-any (must be checked BEFORE plain CAS — more specific):
        # UPDATE containers SET status = :new WHERE id = :cid AND status = ANY(:expected)
        if (
            "update containers" in s
            and "status = :new" in s
            and "any(:expected)" in s
        ):
            expected_list = p.get("expected", [])
            new = str(p.get("new", ""))
            if self.status in expected_list:
                self.status = new
                self.events.append(("cas_any", self.status, new))
                return _R(rowcount=1)
            return _R(rowcount=0)

        # CAS: UPDATE containers SET status = :new WHERE id = :cid AND status = :expected
        if (
            "update containers" in s
            and "status = :new" in s
            and ":expected" in s
        ):
            expected = str(p.get("expected", ""))
            new = str(p.get("new", ""))
            if self.status == expected:
                self.status = new
                self.events.append(("cas", expected, new))
                return _R(rowcount=1)
            return _R(rowcount=0)

        # _load: SELECT id, tenant_id, docker_name, ...
        if "select id, tenant_id, docker_name" in s and "from containers" in s:
            row = (
                str(p.get("cid", "con_a")),
                self.tenant,
                self.docker_name,
                self.volume_name,
                "v1",
                "full",
                "tok_abc",
                "{}",
                {},  # resources
            )
            return _R(first_row=row)

        # current_status: SELECT status FROM containers WHERE id = :cid
        if "select status from containers" in s:
            return _R(scalar_val=self.status, first_row=(self.status,))

        # active_task_count: SELECT count(*) FROM tasks WHERE container_id = :cid
        if "from tasks" in s and "count(" in s and "container_id" in s:
            return _R(scalar_val=self.active)

        # live_count: SELECT count(*) FROM containers WHERE tenant_id = :tid ...
        if "count(*) from containers" in s and "tenant_id" in s:
            return _R(scalar_val=self.live)

        # lru_idle_running: ORDER BY last_task_at
        if "order by" in s and "last_task_at" in s:
            return _R(first_row=None)

        # _set: UPDATE containers SET <fields> WHERE id = :cid (no :new/:expected)
        if "update containers" in s and ":new" not in s:
            return _R(rowcount=1)

        # fail_tasks: UPDATE tasks SET status='failed' ...
        if "update tasks" in s and "status='failed'" in s:
            return _R(rowcount=0)

        # audit insert
        if "insert into audit_log" in s:
            self.audit_rows.append({"stmt": str(stmt)})
            return _R(rowcount=1)

        raise AssertionError(
            f"StatusDB.execute: unhandled SQL:\n{s}\nparams={p!r}"
        )


class _R:
    """Minimal result object."""

    def __init__(
        self,
        rowcount: int = 0,
        scalar_val: object = None,
        first_row: object = None,
    ) -> None:
        self.rowcount = rowcount
        self._scalar_val = scalar_val
        self._first_row = first_row

    def scalar(self) -> object:
        return self._scalar_val

    def first(self) -> object:
        return self._first_row


# ---------------------------------------------------------------------------
# pause tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_rejects_busy_without_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("running", active=1)
    shim, dock = FakeShim(), FakeDocker()
    with pytest.raises(APIError) as ei:
        await lifecycle.pause(db, dock, shim, "con_a", force=False)
    assert ei.value.status_code == 409
    assert ei.value.code == "container_not_runnable"
    assert db.status == "running"  # untouched — no CAS fired


@pytest.mark.asyncio
async def test_pause_force_cancels_then_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("running", active=1)
    shim, dock = FakeShim(), FakeDocker()

    async def fake_stop(  # noqa: ASYNC109
        client: object, name: str, grace_seconds: int
    ) -> None:
        dock.calls.append(("stop", name, grace_seconds))

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)

    await lifecycle.pause(db, dock, shim, "con_a", force=True)

    assert ("con_a", "cancel_all") in shim.calls   # in-flight cancelled first
    assert ("con_a", "/shutdown") in shim.calls     # graceful shutdown before stop
    assert any(c[0] == "stop" for c in dock.calls)  # docker stop called
    assert db.status == "paused"

    # audit row written for force-pause
    assert len(db.audit_rows) >= 1


@pytest.mark.asyncio
async def test_pause_plain_idle_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    db = StatusDB("running", active=0)
    shim, dock = FakeShim(), FakeDocker()

    async def fake_stop(  # noqa: ASYNC109
        client: object, name: str, grace_seconds: int
    ) -> None:
        dock.calls.append(("stop", name))

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)

    await lifecycle.pause(db, dock, shim, "con_a", force=False)
    assert db.status == "paused"


@pytest.mark.asyncio
async def test_pause_commits_running_to_pausing_before_docker_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix #2: the running->pausing CAS is COMMITTED before the slow docker stop.

    Holding the container-row write lock across STOP_GRACE_SECONDS is what caused
    the idle-sweep Postgres deadlocks and the transient DB-pool starvation that
    timed out control-plane routes. Committing first releases the lock before the
    stop (and durably records the transient 'pausing' state, matching the
    irreversible docker stop).
    """
    db = StatusDB("running", active=0)
    shim, dock = FakeShim(), FakeDocker()

    async def fake_stop(  # noqa: ASYNC109
        client: object, name: str, grace_seconds: int
    ) -> None:
        db.events.append(("docker_stop",))

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)

    await lifecycle.pause(db, dock, shim, "con_a", force=False)

    assert db.status == "paused"
    kinds = [e[0] for e in db.events]
    # A commit of the 'pausing' state must occur, and BEFORE the docker stop.
    assert ("commit", "pausing") in db.events, db.events
    assert kinds.index("docker_stop") > kinds.index("commit"), db.events
    # The first commit happens with status already advanced to 'pausing'.
    first_commit = next(e for e in db.events if e[0] == "commit")
    assert first_commit == ("commit", "pausing"), db.events


@pytest.mark.asyncio
async def test_pause_persists_paused_without_caller_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pause() owns its commits now, so the final 'paused' state persists even if
    the caller never commits (the sweep/API still commit; that becomes a no-op)."""
    db = StatusDB("running", active=0)
    shim, dock = FakeShim(), FakeDocker()

    async def fake_stop(client: object, name: str, grace_seconds: int) -> None:  # noqa: ASYNC109
        return None

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)

    await lifecycle.pause(db, dock, shim, "con_a", force=False)
    assert db.status == "paused"
    assert db.commits >= 2  # running->pausing, then pausing->paused
    assert db.rollbacks == 0


# ---------------------------------------------------------------------------
# resume tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_transitions_paused_to_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("paused")
    dock = FakeDocker()

    async def fake_start(client: object, name: str) -> None:
        dock.calls.append(("start", name))

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.resume(db, dock, "con_a")
    assert db.status == "running"
    assert any(c[0] == "start" for c in dock.calls)


@pytest.mark.asyncio
async def test_resume_noop_if_not_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    """If CAS fails (status not 'paused'), resume is a no-op."""
    db = StatusDB("running")
    dock = FakeDocker()

    async def fake_start(client: object, name: str) -> None:
        dock.calls.append(("start", name))

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.resume(db, dock, "con_a")
    assert db.status == "running"   # unchanged
    assert not dock.calls           # docker not touched


# ---------------------------------------------------------------------------
# archive tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_transitions_paused_to_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("paused")
    dock = FakeDocker()

    async def fake_rm(client: object, name: str) -> None:
        dock.calls.append(("rm", name))

    monkeypatch.setattr(lifecycle.docker_ctl, "rm", fake_rm)

    await lifecycle.archive(db, dock, "con_a")
    assert db.status == "archived"
    assert any(c[0] == "rm" for c in dock.calls)


# ---------------------------------------------------------------------------
# rehydrate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rehydrate_transitions_archived_to_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("archived")
    dock = FakeDocker()

    async def fake_run_from_volume(
        client: object, row: dict[str, object], **kwargs: object
    ) -> None:
        dock.calls.append(("run_from_volume", row["docker_name"]))

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle.docker_ctl, "run_from_volume", fake_run_from_volume)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.rehydrate(db, dock, "con_a")
    assert db.status == "running"
    assert any(c[0] == "run_from_volume" for c in dock.calls)


# ---------------------------------------------------------------------------
# recover tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_transitions_error_to_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("error")
    dock = FakeDocker()
    shim = FakeShim()

    async def fake_stop(  # noqa: ASYNC109
        client: object, name: str, grace_seconds: int
    ) -> None:
        dock.calls.append(("stop", name))

    async def fake_exists(client: object, name: str) -> bool:
        return True

    async def fake_start(client: object, name: str) -> None:
        dock.calls.append(("start", name))

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)
    monkeypatch.setattr(lifecycle.docker_ctl, "exists", fake_exists)
    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)
    monkeypatch.setattr(lifecycle.asyncio, "sleep", lambda _: _async_none())

    await lifecycle.recover(db, dock, shim, "con_a")
    assert db.status == "running"

    # audit row written for recover
    assert len(db.audit_rows) >= 1


@pytest.mark.asyncio
async def test_recover_transitions_running_via_transition_from_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recover() accepts running OR recovering as start state (transition_from_any)."""
    db = StatusDB("running")
    dock = FakeDocker()
    shim = FakeShim()

    async def fake_stop(  # noqa: ASYNC109
        client: object, name: str, grace_seconds: int
    ) -> None:
        dock.calls.append(("stop", name))

    async def fake_exists(client: object, name: str) -> bool:
        return True

    async def fake_start(client: object, name: str) -> None:
        dock.calls.append(("start", name))

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", fake_stop)
    monkeypatch.setattr(lifecycle.docker_ctl, "exists", fake_exists)
    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)
    monkeypatch.setattr(lifecycle.asyncio, "sleep", lambda _: _async_none())

    await lifecycle.recover(db, dock, shim, "con_a")
    assert db.status == "running"


# ---------------------------------------------------------------------------
# ensure_running_slot tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_running_slot_under_limit_is_noop() -> None:
    db = StatusDB("running", live=2)
    # live_count returns 2, limit=5 → no slot pressure
    await lifecycle.ensure_running_slot(
        db, FakeDocker(), FakeShim(), "ten_x", limit=5
    )
    # no exception, no pause needed


@pytest.mark.asyncio
async def test_ensure_running_slot_503_when_all_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("running", live=1)

    async def no_victim(_db: object, _tid: str) -> None:
        return None

    async def at_limit(_db: object, _tid: str, exclude: object = None) -> int:
        return 1

    monkeypatch.setattr(lifecycle.admission, "lru_idle_running", no_victim)
    monkeypatch.setattr(lifecycle.admission, "live_count", at_limit)

    with pytest.raises(APIError) as ei:
        await lifecycle.ensure_running_slot(
            db, FakeDocker(), FakeShim(), "ten_x", limit=1
        )
    assert ei.value.status_code == 503
    assert ei.value.code == "running_capacity_exhausted"


@pytest.mark.asyncio
async def test_ensure_running_slot_lru_pauses_victim_when_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("running", live=1)
    paused: dict[str, str] = {}

    async def victim(_db: object, _tid: str) -> str:
        return "con_victim"

    async def at_limit(_db: object, _tid: str, exclude: object = None) -> int:
        return 1

    async def fake_pause(
        _db: object,
        _dock: object,
        _shim: object,
        cid: str,
        *,
        force: bool = False,
    ) -> None:
        paused["cid"] = cid

    monkeypatch.setattr(lifecycle.admission, "lru_idle_running", victim)
    monkeypatch.setattr(lifecycle.admission, "live_count", at_limit)
    monkeypatch.setattr(lifecycle, "pause", fake_pause)

    await lifecycle.ensure_running_slot(
        db, FakeDocker(), FakeShim(), "ten_x", limit=1
    )
    assert paused["cid"] == "con_victim"


# ---------------------------------------------------------------------------
# bring_to_running tests
# ---------------------------------------------------------------------------


async def _fake_ensure(
    _db: object, _dock: object, _shim: object, tid: str, *, limit: int
) -> None:
    pass


@pytest.mark.asyncio
async def test_bring_to_running_noop_if_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("running")
    monkeypatch.setattr(lifecycle, "ensure_running_slot", _fake_ensure)

    await lifecycle.bring_to_running(
        db, FakeDocker(), FakeShim(), "con_a", "ten_x", limit=5
    )
    assert db.status == "running"


@pytest.mark.asyncio
async def test_bring_to_running_resumes_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("paused")
    started: list[str] = []

    async def fake_exists(client: object, name: str) -> bool:
        return True  # container still exists (merely stopped) → docker start

    async def fake_start(client: object, name: str) -> None:
        started.append(name)

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle, "ensure_running_slot", _fake_ensure)
    monkeypatch.setattr(lifecycle.docker_ctl, "exists", fake_exists)
    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.bring_to_running(
        db, FakeDocker(), FakeShim(), "con_a", "ten_x", limit=5
    )
    assert db.status == "running"
    assert started == ["agent-c-a"]  # started the existing container


@pytest.mark.asyncio
async def test_bring_to_running_resume_recreates_missing_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming a paused container whose docker container was removed (pruned/
    reclaimed/host restart) must re-create it from its volume — like the archived
    and reconciler paths — instead of letting docker NotFound escape as a 500."""
    db = StatusDB("paused")
    started: list[str] = []
    recreated: list[str] = []

    async def fake_exists(client: object, name: str) -> bool:
        return False  # backing container is gone

    async def fake_start(client: object, name: str) -> None:
        started.append(name)

    async def fake_run_from_volume(
        client: object, row: dict[str, object], **kwargs: object
    ) -> None:
        recreated.append(str(row["docker_name"]))
        return None

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle, "ensure_running_slot", _fake_ensure)
    monkeypatch.setattr(lifecycle.docker_ctl, "exists", fake_exists)
    monkeypatch.setattr(lifecycle.docker_ctl, "start", fake_start)
    monkeypatch.setattr(lifecycle.docker_ctl, "run_from_volume", fake_run_from_volume)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.bring_to_running(
        db, FakeDocker(), FakeShim(), "con_a", "ten_x", limit=5
    )

    assert db.status == "running"
    assert recreated == ["agent-c-a"]  # re-created from the volume
    assert started == []               # never tried the doomed docker start


@pytest.mark.asyncio
async def test_bring_to_running_rehydrates_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("archived")

    async def fake_run_from_volume(
        client: object, row: dict[str, object], **kwargs: object
    ) -> None:
        pass

    async def fake_readyz(cid: str, *, timeout_s: float, **_kw: object) -> None:
        pass

    monkeypatch.setattr(lifecycle, "ensure_running_slot", _fake_ensure)
    monkeypatch.setattr(lifecycle.docker_ctl, "run_from_volume", fake_run_from_volume)
    monkeypatch.setattr(lifecycle, "_poll_readyz", fake_readyz)

    await lifecycle.bring_to_running(
        db, FakeDocker(), FakeShim(), "con_a", "ten_x", limit=5
    )
    assert db.status == "running"


@pytest.mark.asyncio
async def test_bring_to_running_raises_409_for_non_runnable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = StatusDB("error")
    monkeypatch.setattr(lifecycle, "ensure_running_slot", _fake_ensure)

    with pytest.raises(APIError) as ei:
        await lifecycle.bring_to_running(
            db, FakeDocker(), FakeShim(), "con_a", "ten_x", limit=5
        )
    assert ei.value.status_code == 409
    assert ei.value.code == "container_not_runnable"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _async_none() -> None:
    return None

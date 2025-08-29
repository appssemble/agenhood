import pytest

from control_plane import reconciler
from control_plane.docker_ctl import DockerStateInfo
from control_plane.reconciler import ReconcileAction

pytestmark = pytest.mark.unit


class _RecDB:
    """Records commit/rollback so the reconcile_all orchestration can be asserted."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _missing() -> DockerStateInfo:
    return DockerStateInfo(present=False, status=None, exit_code=None, oom_killed=False)


def _wire_reconcile_all(monkeypatch, rows, *, apply_fn, orphan_fn) -> None:
    """Stub the docker/db seams so reconcile_all exercises only its orchestration."""
    async def fake_rows(db):
        return rows

    async def fake_inspect(client, dn):
        return _missing()

    async def fake_vol(client, vol):
        return True

    monkeypatch.setattr(reconciler, "_all_active_rows", fake_rows)
    monkeypatch.setattr(reconciler.docker_ctl, "inspect_state", fake_inspect)
    monkeypatch.setattr(reconciler, "_volume_exists", fake_vol)
    monkeypatch.setattr(reconciler, "apply_action", apply_fn)
    monkeypatch.setattr(reconciler, "reconcile_orphan_tasks", orphan_fn)


@pytest.mark.asyncio
async def test_apply_action_set_paused_transitions(monkeypatch):
    calls = {}

    async def fake_transition_from_any(db, cid, expected, new):
        calls["paused"] = (cid, new)
        return True

    monkeypatch.setattr(reconciler.lifecycle, "transition_from_any", fake_transition_from_any)
    await reconciler.apply_action(
        db=object(), docker_client=object(), shim=object(),
        cid="con_a", action=ReconcileAction.SET_PAUSED, row={"id": "con_a", "status": "running"},
    )
    assert calls["paused"] == ("con_a", "paused")


@pytest.mark.asyncio
async def test_apply_action_adopt_running_does_not_rearm_already_running(monkeypatch):
    """Regression: ADOPT_RUNNING on a container that is ALREADY 'running' must not
    bump status_changed_at. The periodic reconciler (every 180s) hits this branch
    for every healthy running container; if the adopt CAS accepts 'running' it
    rewrites status_changed_at=now() each pass, and since idle.py keys idle on
    GREATEST(created_at, last_task_at, status_changed_at), the 20-min idle clock is
    reset every 3 minutes and the container NEVER auto-pauses. Only a real
    paused→running adoption should re-arm the timestamp."""
    calls = {}

    async def fake_transition_from_any(db, cid, expected, new):
        calls["expected"] = set(expected)
        calls["new"] = new
        return True

    monkeypatch.setattr(reconciler.lifecycle, "transition_from_any", fake_transition_from_any)
    await reconciler.apply_action(
        db=object(), docker_client=object(), shim=object(),
        cid="con_a", action=ReconcileAction.ADOPT_RUNNING,
        row={"id": "con_a", "status": "running"},
    )
    assert calls["new"] == "running"
    # Must NOT accept an already-running row, or status_changed_at gets rewritten.
    assert "running" not in calls["expected"]
    assert calls["expected"] == {"paused"}


@pytest.mark.asyncio
async def test_apply_action_recover_calls_recover(monkeypatch):
    called = {}

    async def fake_recover(db, dock, shim, cid, *, settings=None, **kwargs):
        called["cid"] = cid

    async def fake_audit(*args, **kwargs):
        pass

    monkeypatch.setattr(reconciler.lifecycle, "recover", fake_recover)
    monkeypatch.setattr(reconciler, "audit", fake_audit)
    await reconciler.apply_action(
        db=object(), docker_client=object(), shim=object(),
        cid="con_a", action=ReconcileAction.RECOVER, row={"id": "con_a", "status": "running"},
    )
    assert called["cid"] == "con_a"


@pytest.mark.asyncio
async def test_apply_action_recover_forwards_settings(monkeypatch):
    """Regression: reconciler-triggered recover MUST forward `settings` to
    lifecycle.recover. Without it, recover() falls back to settings=None and
    recreates the agent container on Docker's default `bridge` network instead
    of the configured internal network, leaving it unreachable by the control
    plane (task submission hangs in `pending`)."""
    captured = {}

    async def fake_recover(db, dock, shim, cid, *, settings=None, **kwargs):
        captured["settings"] = settings

    async def fake_audit(*args, **kwargs):
        pass

    monkeypatch.setattr(reconciler.lifecycle, "recover", fake_recover)
    monkeypatch.setattr(reconciler, "audit", fake_audit)
    sentinel = object()
    await reconciler.apply_action(
        db=object(), docker_client=object(), shim=object(),
        cid="con_a", action=ReconcileAction.RECOVER,
        row={"id": "con_a", "status": "running"}, settings=sentinel,
    )
    assert captured["settings"] is sentinel


@pytest.mark.asyncio
async def test_reconcile_tasks_fails_orphans():
    executed = {}

    class DB:
        async def execute(self, stmt, params=None):
            s = str(stmt).lower()
            if "update tasks" in s:
                executed["sql"] = s
                executed["params"] = params

            class R:
                rowcount = 1

                def first(self):
                    return None

            return R()

    await reconciler.reconcile_orphan_tasks(DB(), healthy_running_ids={"con_ok"})
    assert "container_restarted" in str(executed["params"])  # code passed
    assert (
        "not in" in executed["sql"]
        or "<> all" in executed["sql"]
        or "!= all" in executed["sql"]
    )


@pytest.mark.asyncio
async def test_reconcile_all_commits_each_row(monkeypatch):
    # Each row's reconcile action must be committed, plus the orphan-task pass.
    # Without commits the whole sweep rolls back when the session closes and no
    # reconciliation persists.
    rows = [
        {"id": "con_1", "docker_name": "d1", "volume_name": "v1", "status": "paused"},
        {"id": "con_2", "docker_name": "d2", "volume_name": "v2", "status": "paused"},
    ]

    async def ok_apply(**kwargs):
        return None

    async def ok_orphan(db, healthy):
        return None

    _wire_reconcile_all(monkeypatch, rows, apply_fn=ok_apply, orphan_fn=ok_orphan)
    db = _RecDB()
    await reconciler.reconcile_all(db, object(), object())

    assert db.commits == 3   # two rows + orphan-task pass
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_reconcile_all_isolates_failing_row(monkeypatch):
    # The bug: a failing row's aborted transaction was never rolled back, so it
    # poisoned every subsequent row (InFailedSQLTransactionError cascade). A row
    # that raises must be rolled back and must NOT stop the remaining rows from
    # being applied and committed.
    rows = [
        {"id": "boom", "docker_name": "d0", "volume_name": "v0", "status": "running"},
        {"id": "con_ok", "docker_name": "d1", "volume_name": "v1", "status": "paused"},
    ]
    applied = []

    async def flaky_apply(*, cid, **kwargs):
        applied.append(cid)
        if cid == "boom":
            raise RuntimeError("deadlock detected")

    async def ok_orphan(db, healthy):
        return None

    _wire_reconcile_all(monkeypatch, rows, apply_fn=flaky_apply, orphan_fn=ok_orphan)
    db = _RecDB()
    await reconciler.reconcile_all(db, object(), object())

    assert applied == ["boom", "con_ok"]  # no cascade: con_ok still processed
    assert db.rollbacks == 1              # boom's aborted txn cleared
    assert db.commits == 2                # con_ok + orphan-task pass


@pytest.mark.asyncio
async def test_reconcile_all_rolls_back_orphan_failure(monkeypatch):
    # A failure in the orphan-task pass must roll back rather than leak an aborted
    # transaction back to the sweep loop.
    async def ok_apply(**kwargs):
        return None

    async def boom_orphan(db, healthy):
        raise RuntimeError("orphan update failed")

    _wire_reconcile_all(monkeypatch, [], apply_fn=ok_apply, orphan_fn=boom_orphan)
    db = _RecDB()
    await reconciler.reconcile_all(db, object(), object())

    assert db.commits == 0
    assert db.rollbacks == 1

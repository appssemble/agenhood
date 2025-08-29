"""ReconcileAction completeness gate: every action produced + dispatched.

Two meta-gates:
1. Producer gate — DECISION_CASES collectively yield every ReconcileAction
   member via reconcile_decision.  Adding a new enum value without a matching
   row makes the gate fail immediately.
2. Dispatch gate — apply_action accepts every ReconcileAction without raising.
   A new enum value with no if-branch in apply_action falls through silently;
   this gate catches that when combined with the producer gate above.

Per-branch side-effect assertions live in test_reconcile_executor.py.  This
file adds coverage for the action branches that test_reconcile_executor.py
does not exercise (SET_ERROR, STOP_TO_PAUSED, FINISH_TO_RUNNING,
FINISH_TO_PAUSED, DESTROY_PARTIAL_TO_ERROR, RM_TO_ARCHIVED, SET_ARCHIVED,
RM_STALE_STAY_ARCHIVED, FINISH_DESTROY, FINISH_DELETE, NOOP).
"""
from __future__ import annotations

import pytest

import control_plane.reconciler as Rmod
from control_plane.docker_ctl import DockerStateInfo
from control_plane.reconciler import ReconcileAction, reconcile_decision

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docker(present: bool = True, status: str = "running",
            exit_code: int | None = None, oom: bool = False) -> DockerStateInfo:
    return DockerStateInfo(
        present=present, status=status, exit_code=exit_code, oom_killed=oom
    )


# ---------------------------------------------------------------------------
# Decision matrix
# (db_status, docker, readyz_ok, volume_exists) -> expected action.
#
# Each row targets one ReconcileAction.  The producer meta-gate below asserts
# that together these rows cover *every* member of the enum — so a new
# ReconcileAction that has no row here causes that test to fail.
# ---------------------------------------------------------------------------

DECISION_CASES: list[tuple[str, DockerStateInfo, bool, bool, ReconcileAction]] = [
    # NOOP: paused + container exited → consistent rest
    ("paused",       _docker(status="exited"),              False, True,  ReconcileAction.NOOP),
    # ADOPT_RUNNING: running db + container up and ready → re-arm (paused→running CAS)
    ("running",      _docker(status="running"),             True,  True,  ReconcileAction.ADOPT_RUNNING),  # noqa: E501
    # RECOVER: running db + container up but NOT ready → recovery routine
    ("running",      _docker(status="running"),             False, True,  ReconcileAction.RECOVER),
    # SET_PAUSED: running db + clean exit (code 0, no OOM) + volume present
    ("running",      _docker(status="exited", exit_code=0), False, True,  ReconcileAction.SET_PAUSED),  # noqa: E501
    # SET_ERROR: running db + container gone + no volume → unrecoverable
    ("running",      _docker(present=False),                False, False, ReconcileAction.SET_ERROR),  # noqa: E501
    # STOP_TO_PAUSED: pausing db + container still up → re-issue stop
    ("pausing",      _docker(status="running"),             True,  True,  ReconcileAction.STOP_TO_PAUSED),  # noqa: E501
    # FINISH_TO_RUNNING: provisioning db + container up and ready → adopt as running
    ("provisioning", _docker(status="running"),             True,  True,  ReconcileAction.FINISH_TO_RUNNING),  # noqa: E501
    # FINISH_TO_PAUSED: pausing db + container already exited → mark paused
    ("pausing",      _docker(status="exited"),              False, True,  ReconcileAction.FINISH_TO_PAUSED),  # noqa: E501
    # DESTROY_PARTIAL_TO_ERROR: provisioning db + container exited without readyz → error
    ("provisioning", _docker(status="exited"),              False, True,  ReconcileAction.DESTROY_PARTIAL_TO_ERROR),  # noqa: E501
    # RM_TO_ARCHIVED: archiving db + container still present → rm then archived
    ("archiving",    _docker(status="exited"),              False, True,  ReconcileAction.RM_TO_ARCHIVED),  # noqa: E501
    # SET_ARCHIVED: archiving db + container already gone → mark archived
    ("archiving",    _docker(present=False),                False, True,  ReconcileAction.SET_ARCHIVED),  # noqa: E501
    # RM_STALE_STAY_ARCHIVED: archived db + stale container present → rm, keep archived
    ("archived",     _docker(status="exited"),              False, True,  ReconcileAction.RM_STALE_STAY_ARCHIVED),  # noqa: E501
    # FINISH_DESTROY: destroying db → complete the destroy intent
    ("destroying",   _docker(present=False),                False, False, ReconcileAction.FINISH_DESTROY),  # noqa: E501
    # FINISH_DELETE: deleting db → complete the hard delete
    ("deleting",     _docker(present=False),                False, False, ReconcileAction.FINISH_DELETE),  # noqa: E501
    # SET_PAUSED via resuming: resuming + container absent/not-ready → safe-rest as paused
    ("resuming",     _docker(present=False),                False, True,  ReconcileAction.SET_PAUSED),  # noqa: E501
    # RECOVER via missing+volume: running + container gone but volume present → recovery
    ("running",      _docker(present=False),                False, True,  ReconcileAction.RECOVER),
    # RECOVER via recovering status: db in recovering state → re-enter recovery routine
    ("recovering",   _docker(present=False),                False, False, ReconcileAction.RECOVER),
]

# CELL_CASES: the 3 branches with no prior cell coverage in this file.  DECISION_CASES
# (full set above) is kept for the producer gate.  The cell test parametrizes only
# these 3 rows to avoid duplicating the 14 cases already covered in
# test_reconcile_decision.py — but these specific branches were absent there.
CELL_CASES: list[tuple[str, DockerStateInfo, bool, bool, ReconcileAction]] = [
    ("resuming",   _docker(present=False), False, True,  ReconcileAction.SET_PAUSED),
    ("running",    _docker(present=False), False, True,  ReconcileAction.RECOVER),
    ("recovering", _docker(present=False), False, False, ReconcileAction.RECOVER),
]


@pytest.mark.parametrize("db_status,docker,readyz,vol,expected", CELL_CASES)
def test_reconcile_decision_cell(db_status, docker, readyz, vol, expected):
    got = reconcile_decision(db_status, docker, readyz_ok=readyz, volume_exists=vol)
    assert got is expected


def test_every_reconcile_action_is_produced_by_a_decision_case():
    """Producer meta-gate: every ReconcileAction member is reachable via
    reconcile_decision under some documented input.

    A new enum value added to ReconcileAction without a corresponding
    DECISION_CASES row causes this assertion to fail — the gate bites.
    """
    produced = {c[-1] for c in DECISION_CASES}
    assert produced == set(ReconcileAction), (
        "ReconcileAction members without a DECISION_CASES row "
        "(add a canonical input row for each): "
        f"{sorted(a.value for a in set(ReconcileAction) - produced)}"
    )


# ---------------------------------------------------------------------------
# Executor dispatch gate
# ---------------------------------------------------------------------------

class _FakeDB:
    """Minimal async DB stub that records calls."""

    def __init__(self) -> None:
        self.calls: list = []

    async def execute(self, *a, **k):
        self.calls.append(("execute", a))

        class _R:
            rowcount = 1

            def first(self_inner):
                return None

            def scalar_one(self_inner):
                return 0

        return _R()

    async def commit(self) -> None:
        self.calls.append(("commit", ()))

    async def rollback(self) -> None:
        self.calls.append(("rollback", ()))


class _FakeShim:
    """Shim stub whose post() is a no-op coroutine."""

    async def post(self, cid: str, path: str, **kwargs) -> None:
        pass


def _patch_all_seams(monkeypatch) -> None:
    """Stub every guarded helper called inside apply_action branches.

    Seams patched (all at reconciler-module scope so monkeypatch restores them):
    - lifecycle.transition_from_any  — called by most action branches
    - lifecycle.recover              — RECOVER branch
    - lifecycle._set                 — SET_ERROR, DESTROY_PARTIAL_TO_ERROR
    - lifecycle.fail_tasks           — SET_ERROR
    - docker_ctl.stop                — STOP_TO_PAUSED
    - docker_ctl.rm                  — DESTROY_PARTIAL_TO_ERROR, RM_TO_ARCHIVED,
                                       RM_STALE_STAY_ARCHIVED, FINISH_DESTROY,
                                       FINISH_DELETE
    - docker_ctl.volume_rm           — FINISH_DESTROY (intent=True), FINISH_DELETE
    - reconciler.audit               — RECOVER, SET_ERROR, DESTROY_PARTIAL_TO_ERROR,
                                       FINISH_DESTROY, FINISH_DELETE
    """

    async def _noop(*a, **k) -> None:
        return None

    async def _true(*a, **k) -> bool:
        return True

    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", _true)
    monkeypatch.setattr(Rmod.lifecycle, "recover", _noop)
    monkeypatch.setattr(Rmod.lifecycle, "_set", _noop)
    monkeypatch.setattr(Rmod.lifecycle, "fail_tasks", _noop)

    monkeypatch.setattr(Rmod.docker_ctl, "stop", _noop)
    monkeypatch.setattr(Rmod.docker_ctl, "rm", _noop)
    monkeypatch.setattr(Rmod.docker_ctl, "volume_rm", _noop)

    monkeypatch.setattr(Rmod, "audit", _noop)


# Base row for executor tests; destroy_delete_volume=False avoids the
# optional volume_rm call inside FINISH_DESTROY so we only need docker_ctl.rm
# mocked (which we do anyway).
_BASE_ROW: dict[str, object] = {
    "id": "con_1",
    "docker_name": "dn",
    "volume_name": "vol",
    "status": "running",
    "destroy_delete_volume": False,
}


# ---------------------------------------------------------------------------
# Dispatch-gate effect map
#
# Maps each ReconcileAction to the ONE observable it must produce in apply_action.
# Format: (observed_key, predicate(calls) → bool) or None for NOOP.
#
# If a branch is removed from apply_action, the observed list for its key stays
# empty and the predicate returns False → the parametrized test fails.  A new
# enum member with no entry here causes the mapping-completeness assertion to
# fail before apply_action is even called.
# ---------------------------------------------------------------------------

DISPATCH_EFFECTS: dict = {
    ReconcileAction.NOOP: None,  # sentinel: all seams must be silent
    ReconcileAction.RECOVER: (
        "recover",
        lambda c: bool(c),
    ),
    ReconcileAction.ADOPT_RUNNING: (
        "transition_new",
        lambda c: any(new == "running" and "paused" in exp for exp, new in c),
    ),
    ReconcileAction.SET_PAUSED: (
        "transition_new",
        lambda c: any(new == "paused" and "running" in exp for exp, new in c),
    ),
    ReconcileAction.SET_ERROR: (
        "set_calls",
        lambda c: any(
            f.get("error_message") == "container and volume missing on reconcile"
            for f in c
        ),
    ),
    ReconcileAction.STOP_TO_PAUSED: (
        "stop_calls",
        lambda c: bool(c),
    ),
    ReconcileAction.FINISH_TO_RUNNING: (
        "transition_new",
        lambda c: any(new == "running" and "provisioning" in exp for exp, new in c),
    ),
    ReconcileAction.FINISH_TO_PAUSED: (
        "transition_new",
        lambda c: any(new == "paused" and "pausing" in exp for exp, new in c),
    ),
    ReconcileAction.DESTROY_PARTIAL_TO_ERROR: (
        "set_calls",
        lambda c: any(f.get("error_message") == "provisioning interrupted" for f in c),
    ),
    ReconcileAction.RM_TO_ARCHIVED: (
        "transition_new",
        lambda c: any(new == "archived" and "archiving" in exp for exp, new in c),
    ),
    ReconcileAction.SET_ARCHIVED: (
        "transition_new",
        lambda c: any(new == "archived" for _, new in c),
    ),
    ReconcileAction.RM_STALE_STAY_ARCHIVED: (
        "rm_calls",
        lambda c: bool(c),
    ),
    ReconcileAction.FINISH_DESTROY: (
        "transition_new",
        lambda c: any(new == "destroyed" for _, new in c),
    ),
    ReconcileAction.FINISH_DELETE: (
        "vol_rm_calls",
        lambda c: bool(c),
    ),
}


@pytest.mark.parametrize("action", list(ReconcileAction), ids=lambda a: a.value)
async def test_apply_action_dispatches_every_action(action, monkeypatch):
    """Dispatch gate: apply_action must invoke a DISTINCT, action-specific side-effect.

    The DISPATCH_EFFECTS mapping must cover exactly set(ReconcileAction).  A new
    enum member with no entry causes the completeness assertion to fail immediately,
    forcing the author to declare the expected observable for the new branch.

    A fall-through action (branch missing from apply_action) produces no spy calls,
    so its predicate evaluates to False and the test fails — the gate bites.
    """
    # Completeness: new enum member without a DISPATCH_EFFECTS entry fails here.
    assert set(DISPATCH_EFFECTS) == set(ReconcileAction), (
        "DISPATCH_EFFECTS is missing entries for: "
        + str(sorted(a.value for a in set(ReconcileAction) - set(DISPATCH_EFFECTS)))
    )

    _patch_all_seams(monkeypatch)
    observed: dict = {
        "recover": [],
        "transition_new": [],
        "set_calls": [],
        "rm_calls": [],
        "vol_rm_calls": [],
        "stop_calls": [],
    }

    async def spy_recover(db, dc, shim, cid, *, settings=None):
        observed["recover"].append(cid)

    async def spy_transition(db, cid, expected, new):
        observed["transition_new"].append((set(expected), new))
        return True

    async def spy_set(db, cid, **fields):
        observed["set_calls"].append(fields)

    async def spy_rm(dc, dn):
        observed["rm_calls"].append(dn)

    async def spy_vol_rm(dc, vol):
        observed["vol_rm_calls"].append(vol)

    async def spy_stop(dc, dn, grace):
        observed["stop_calls"].append(dn)

    monkeypatch.setattr(Rmod.lifecycle, "recover", spy_recover)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)
    monkeypatch.setattr(Rmod.lifecycle, "_set", spy_set)
    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.docker_ctl, "volume_rm", spy_vol_rm)
    monkeypatch.setattr(Rmod.docker_ctl, "stop", spy_stop)

    await Rmod.apply_action(
        db=_FakeDB(),
        docker_client=object(),
        shim=_FakeShim(),
        cid="con_1",
        action=action,
        row=dict(_BASE_ROW),
        settings=None,
    )

    effect = DISPATCH_EFFECTS[action]
    if effect is None:
        # NOOP: every seam must stay silent
        for key in ("recover", "transition_new", "set_calls", "rm_calls", "vol_rm_calls", "stop_calls"):  # noqa: E501
            assert not observed[key], f"NOOP must not invoke {key!r}"
    else:
        obs_key, predicate = effect
        assert predicate(observed[obs_key]), (
            f"{action.value}: expected effect on {obs_key!r} not observed. "
            f"Got: {observed[obs_key]}"
        )


# ---------------------------------------------------------------------------
# Executor branch coverage (branches not covered by test_reconcile_executor.py)
# ---------------------------------------------------------------------------

async def test_apply_action_noop_returns_without_side_effects(monkeypatch):
    """NOOP acquires the container lock and returns immediately."""
    _patch_all_seams(monkeypatch)
    transition_calls: list = []

    async def spy_transition(*a, **k) -> bool:
        transition_calls.append(a)
        return True

    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)
    db = _FakeDB()
    await Rmod.apply_action(
        db=db, docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.NOOP, row=dict(_BASE_ROW),
    )
    assert transition_calls == [], "NOOP must not call transition_from_any"
    assert db.calls == [], "NOOP must not touch the database"


async def test_apply_action_set_error_transitions_and_audits(monkeypatch):
    """SET_ERROR: transition → running/provisioning → error, sets error_message,
    fails tasks, writes audit row."""
    _patch_all_seams(monkeypatch)
    observed: dict[str, object] = {}

    async def spy_transition(db, cid, expected, new):
        observed["transition_expected"] = set(expected)
        observed["transition_new"] = new
        return True

    async def spy_set(db, cid, **fields):
        observed.setdefault("set_fields", []).append(fields)

    async def spy_fail(db, cid, *, code):
        observed["fail_code"] = code

    async def spy_audit(db, *, actor_type, action, target_type, target_id, details, actor_id=None):
        observed["audit_action"] = action
        observed["audit_details"] = details

    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)
    monkeypatch.setattr(Rmod.lifecycle, "_set", spy_set)
    monkeypatch.setattr(Rmod.lifecycle, "fail_tasks", spy_fail)
    monkeypatch.setattr(Rmod, "audit", spy_audit)

    row = dict(_BASE_ROW, status="running", _docker_status="missing")
    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.SET_ERROR, row=row,
    )
    assert observed["transition_new"] == "error"
    # CAS guard must cover both statuses that can go unrecoverable.
    assert "running" in observed["transition_expected"]
    assert "provisioning" in observed["transition_expected"]
    assert observed["fail_code"] == "container_restarted"
    assert observed["audit_action"] == "container.reconciled"
    assert observed["audit_details"]["to"] == "error"
    # error_message must be written so operators know why the container failed.
    set_fields = observed.get("set_fields", [])
    assert any(
        f.get("error_message") == "container and volume missing on reconcile"
        for f in set_fields
    ), f"lifecycle._set not called with expected error_message; got: {set_fields}"


async def test_apply_action_stop_to_paused_stops_container(monkeypatch):
    """STOP_TO_PAUSED: calls docker_ctl.stop then transitions to paused."""
    _patch_all_seams(monkeypatch)
    stop_calls: list = []
    transition_calls: list = []

    async def spy_stop(client, dn, grace):
        stop_calls.append((dn, grace))

    async def spy_transition(db, cid, expected, new):
        transition_calls.append((set(expected), new))
        return True

    monkeypatch.setattr(Rmod.docker_ctl, "stop", spy_stop)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.STOP_TO_PAUSED, row=dict(_BASE_ROW),
    )
    assert len(stop_calls) == 1
    assert stop_calls[0][0] == "dn"
    assert any(new == "paused" for _, new in transition_calls)


async def test_apply_action_finish_to_running_transitions(monkeypatch):
    """FINISH_TO_RUNNING: transitions from provisioning/resuming → running."""
    _patch_all_seams(monkeypatch)
    observed: dict[str, object] = {}

    async def spy_transition(db, cid, expected, new):
        observed["expected"] = set(expected)
        observed["new"] = new
        return True

    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.FINISH_TO_RUNNING, row=dict(_BASE_ROW),
    )
    assert observed["new"] == "running"
    assert "provisioning" in observed["expected"]
    assert "resuming" in observed["expected"]


async def test_apply_action_finish_to_paused_transitions(monkeypatch):
    """FINISH_TO_PAUSED: transitions from pausing → paused."""
    _patch_all_seams(monkeypatch)
    observed: dict[str, object] = {}

    async def spy_transition(db, cid, expected, new):
        observed["expected"] = set(expected)
        observed["new"] = new
        return True

    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.FINISH_TO_PAUSED, row=dict(_BASE_ROW),
    )
    assert observed["new"] == "paused"
    assert "pausing" in observed["expected"]


async def test_apply_action_destroy_partial_to_error_rms_then_errors(monkeypatch):
    """DESTROY_PARTIAL_TO_ERROR: rm partial container, transition to error, sets
    error_message, writes audit row."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    transition_calls: list = []
    set_calls: list = []
    audit_calls: list = []

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_transition(db, cid, expected, new):
        transition_calls.append(new)
        return True

    async def spy_set(db, cid, **fields):
        set_calls.append(fields)

    async def spy_audit(db, **kwargs):
        audit_calls.append(kwargs.get("details", {}))

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)
    monkeypatch.setattr(Rmod.lifecycle, "_set", spy_set)
    monkeypatch.setattr(Rmod, "audit", spy_audit)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.DESTROY_PARTIAL_TO_ERROR, row=dict(_BASE_ROW),
    )
    assert rm_calls == ["dn"]
    assert "error" in transition_calls
    assert any(d.get("to") == "error" for d in audit_calls)
    # error_message must be written so operators know why provisioning failed.
    assert any(
        f.get("error_message") == "provisioning interrupted" for f in set_calls
    ), f"lifecycle._set not called with expected error_message; got: {set_calls}"


async def test_apply_action_rm_to_archived_rms_and_transitions(monkeypatch):
    """RM_TO_ARCHIVED: rm stopped container then mark archived."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    transition_calls: list = []

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_transition(db, cid, expected, new):
        transition_calls.append(new)
        return True

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.RM_TO_ARCHIVED, row=dict(_BASE_ROW),
    )
    assert rm_calls == ["dn"]
    assert "archived" in transition_calls


async def test_apply_action_set_archived_transitions(monkeypatch):
    """SET_ARCHIVED: container already gone; just transition → archived."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    observed: dict[str, object] = {}

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_transition(db, cid, expected, new):
        observed["new"] = new
        return True

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.SET_ARCHIVED, row=dict(_BASE_ROW),
    )
    assert rm_calls == [], "SET_ARCHIVED must not rm when container is already gone"
    assert observed["new"] == "archived"


async def test_apply_action_rm_stale_stay_archived_rms_only(monkeypatch):
    """RM_STALE_STAY_ARCHIVED: rm stale container; status stays archived (no transition)."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    transition_calls: list = []

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_transition(db, cid, expected, new):
        transition_calls.append(new)
        return True

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)

    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.RM_STALE_STAY_ARCHIVED, row=dict(_BASE_ROW),
    )
    assert rm_calls == ["dn"], "RM_STALE_STAY_ARCHIVED must remove the stale container"
    assert transition_calls == [], "status must NOT change — must stay archived"


async def test_apply_action_finish_destroy_rms_and_transitions_to_destroyed(monkeypatch):
    """FINISH_DESTROY: rm container, skip volume (intent=False), transition → destroyed, audit."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    vol_rm_calls: list = []
    transition_calls: list = []
    audit_calls: list = []

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_vol_rm(client, vol):
        vol_rm_calls.append(vol)

    async def spy_transition(db, cid, expected, new):
        transition_calls.append(new)
        return True

    async def spy_audit(db, **kwargs):
        audit_calls.append(kwargs.get("details", {}))

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.docker_ctl, "volume_rm", spy_vol_rm)
    monkeypatch.setattr(Rmod.lifecycle, "transition_from_any", spy_transition)
    monkeypatch.setattr(Rmod, "audit", spy_audit)

    row = dict(_BASE_ROW, status="destroying", destroy_delete_volume=False)
    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.FINISH_DESTROY, row=row,
    )
    assert rm_calls == ["dn"]
    assert vol_rm_calls == [], "volume should not be removed when intent=False"
    assert "destroyed" in transition_calls
    assert any(d.get("to") == "destroyed" for d in audit_calls)
    assert any(d.get("from") == "destroying" for d in audit_calls)


async def test_apply_action_finish_destroy_rms_volume_when_intent_true(monkeypatch):
    """FINISH_DESTROY: when destroy_delete_volume=True, also rm the volume."""
    _patch_all_seams(monkeypatch)
    vol_rm_calls: list = []

    async def spy_vol_rm(client, vol):
        vol_rm_calls.append(vol)

    monkeypatch.setattr(Rmod.docker_ctl, "volume_rm", spy_vol_rm)

    row = dict(_BASE_ROW, destroy_delete_volume=True, volume_name="my_vol")
    await Rmod.apply_action(
        db=_FakeDB(), docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.FINISH_DESTROY, row=row,
    )
    assert vol_rm_calls == ["my_vol"]


async def test_apply_action_finish_delete_removes_row_and_audits(monkeypatch):
    """FINISH_DELETE: rm container, rm volume, DELETE tasks + containers rows, audit."""
    _patch_all_seams(monkeypatch)
    rm_calls: list = []
    vol_rm_calls: list = []
    audit_calls: list = []

    async def spy_rm(client, dn):
        rm_calls.append(dn)

    async def spy_vol_rm(client, vol):
        vol_rm_calls.append(vol)

    async def spy_audit(db, **kwargs):
        audit_calls.append(kwargs.get("details", {}))

    monkeypatch.setattr(Rmod.docker_ctl, "rm", spy_rm)
    monkeypatch.setattr(Rmod.docker_ctl, "volume_rm", spy_vol_rm)
    monkeypatch.setattr(Rmod, "audit", spy_audit)

    db = _FakeDB()
    row = dict(_BASE_ROW, volume_name="my_vol")
    await Rmod.apply_action(
        db=db, docker_client=object(), shim=_FakeShim(),
        cid="con_1", action=ReconcileAction.FINISH_DELETE, row=row,
    )
    assert rm_calls == ["dn"]
    assert vol_rm_calls == ["my_vol"]
    executed_sqls = [str(a[0]).lower() for _, a in db.calls if _ == "execute"]
    assert any("delete from tasks" in s for s in executed_sqls)
    assert any("delete from containers" in s for s in executed_sqls)
    assert any(d.get("to") == "deleted" for d in audit_calls)

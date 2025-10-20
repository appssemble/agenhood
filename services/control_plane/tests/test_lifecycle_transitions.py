from __future__ import annotations

import pytest

from control_plane import lifecycle

pytestmark = pytest.mark.unit


# --- the legal transition table (index §4 states; spec §4.10 machine) ---
LEGAL = {
    ("provisioning", "running"),
    ("provisioning", "error"),
    ("running", "pausing"),
    ("running", "recovering"),
    ("pausing", "paused"),
    ("paused", "resuming"),
    ("paused", "archiving"),
    ("resuming", "running"),
    ("resuming", "paused"),       # reconciler safe-rest (spec §4.11)
    ("archiving", "archived"),
    ("archived", "provisioning"), # rehydrate (spec §4.13)
    ("archived", "destroying"),   # reclaim (spec §4.13)
    ("recovering", "running"),
    ("recovering", "error"),
    ("error", "provisioning"),    # recover (spec §4.12)
    ("destroying", "destroyed"),
}
# destroy is allowed from any non-terminal state
DESTROYABLE_FROM = {
    "provisioning", "running", "pausing", "paused", "resuming",
    "archiving", "archived", "recovering", "error",
}

ILLEGAL = [
    ("running", "running"),
    ("running", "paused"),        # must pass through pausing
    ("running", "archived"),
    ("paused", "running"),        # must pass through resuming
    ("paused", "archived"),       # must pass through archiving
    ("archived", "running"),      # must pass through provisioning
    ("destroyed", "running"),     # terminal
    ("error", "running"),         # only via recover→provisioning
    ("provisioning", "paused"),
    ("pausing", "running"),
]


def test_every_legal_transition_is_allowed():
    for src, dst in LEGAL:
        assert lifecycle.is_legal_transition(src, dst), f"{src}->{dst} should be legal"


def test_destroy_allowed_from_any_nonterminal():
    for src in DESTROYABLE_FROM:
        assert lifecycle.is_legal_transition(src, "destroying"), (
            f"{src}->destroying should be legal"
        )


def test_representative_illegal_transitions_are_rejected():
    for src, dst in ILLEGAL:
        assert not lifecycle.is_legal_transition(src, dst), f"{src}->{dst} should be illegal"


# --- CAS guard ---
class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeDB:
    def __init__(self, rowcount: int) -> None:
        self._rowcount = rowcount
        self.executed: list[tuple[str, object]] = []

    async def execute(self, stmt: object, params: object = None) -> FakeResult:
        self.executed.append((str(stmt), params))
        return FakeResult(self._rowcount)


@pytest.mark.asyncio
async def test_transition_returns_true_when_status_matched():
    db = FakeDB(rowcount=1)
    ok = await lifecycle.transition(db, "con_x", "running", "pausing")
    assert ok is True


@pytest.mark.asyncio
async def test_transition_returns_false_when_status_changed_underneath():
    db = FakeDB(rowcount=0)
    ok = await lifecycle.transition(db, "con_x", "running", "pausing")
    assert ok is False  # the CAS guard: someone else moved the row


@pytest.mark.asyncio
async def test_transition_from_any_matches_one_of_expected():
    db = FakeDB(rowcount=1)
    ok = await lifecycle.transition_from_any(db, "con_x", {"running", "recovering"}, "recovering")
    assert ok is True


@pytest.mark.asyncio
async def test_transition_from_any_false_when_none_match():
    db = FakeDB(rowcount=0)
    ok = await lifecycle.transition_from_any(db, "con_x", {"running", "recovering"}, "recovering")
    assert ok is False


# destroy reaches 'archived' from any live state via 'archiving' (spec §4.2)
ARCHIVING_SOURCES = {
    "provisioning", "running", "pausing", "paused", "resuming", "recovering", "error",
}


def test_archiving_legal_from_live_states():
    for src in ARCHIVING_SOURCES:
        assert lifecycle.is_legal_transition(src, "archiving"), src


def test_archiving_illegal_from_archived_or_terminal():
    assert not lifecycle.is_legal_transition("archived", "archiving")
    assert not lifecycle.is_legal_transition("destroying", "archiving")
    assert not lifecycle.is_legal_transition("destroyed", "archiving")


def test_deleting_legal_from_any_state():
    for src in [
        "provisioning", "running", "pausing", "paused", "resuming",
        "archiving", "archived", "recovering", "error", "destroying", "destroyed",
    ]:
        assert lifecycle.is_legal_transition(src, "deleting"), src


# --- per-container lock registry ---
def test_container_lock_is_stable_per_id():
    a1 = lifecycle.container_lock("con_a")
    a2 = lifecycle.container_lock("con_a")
    b = lifecycle.container_lock("con_b")
    assert a1 is a2
    assert a1 is not b

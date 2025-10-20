from __future__ import annotations

import itertools

import pytest

from control_plane import lifecycle

pytestmark = pytest.mark.unit

ALL_STATES = sorted(
    {s for edge in lifecycle._LEGAL_TRANSITIONS for s in edge} | {"deleting"}
)

# The full legal-transition table, mirrored here so the gate fails LOUDLY when
# the source set changes without a deliberate review of this file.
EXPECTED_LEGAL: set[tuple[str, str]] = {
    ("provisioning", "running"),
    ("provisioning", "error"),
    ("running", "pausing"),
    ("running", "recovering"),
    ("pausing", "paused"),
    ("paused", "resuming"),
    ("paused", "archiving"),
    ("resuming", "running"),
    ("resuming", "paused"),
    ("archiving", "archived"),
    ("archived", "provisioning"),
    ("archived", "destroying"),
    ("recovering", "running"),
    ("recovering", "error"),
    ("error", "provisioning"),
    ("destroying", "destroyed"),
}


def test_legal_transition_table_is_locked():
    """Meta-gate: a new state/edge cannot ship without updating this table."""
    assert lifecycle._LEGAL_TRANSITIONS == EXPECTED_LEGAL


@pytest.mark.parametrize("src,dst", sorted(EXPECTED_LEGAL))
def test_every_legal_edge_is_allowed(src, dst):
    assert lifecycle.is_legal_transition(src, dst) is True


def test_illegal_edges_are_rejected():
    legal = set(EXPECTED_LEGAL)
    for src, dst in itertools.product(ALL_STATES, ALL_STATES):
        # NB: self-loops are NOT skipped — every cell must be asserted so a
        # future `if src == dst: return True` special-rule slip is caught. The
        # only legal self-loop (deleting→deleting) is handled by the
        # dst == "deleting" guard below; all others must be is_legal == False.
        if (src, dst) in legal:
            continue
        # Special always-legal rules are asserted separately below.
        if dst == "deleting":
            continue
        if dst == "destroying" and src in lifecycle._NON_TERMINAL:
            continue
        if dst == "archiving" and src in lifecycle._ARCHIVING_SOURCES:
            continue
        assert lifecycle.is_legal_transition(src, dst) is False, (src, dst)


@pytest.mark.parametrize("src", ALL_STATES)
def test_deleting_is_legal_from_any_state(src):
    assert lifecycle.is_legal_transition(src, "deleting") is True


@pytest.mark.parametrize("src", sorted(lifecycle._NON_TERMINAL))
def test_destroying_is_legal_from_any_non_terminal(src):
    assert lifecycle.is_legal_transition(src, "destroying") is True


@pytest.mark.parametrize("src", sorted(lifecycle._ARCHIVING_SOURCES))
def test_archiving_is_legal_from_archiving_sources(src):
    assert lifecycle.is_legal_transition(src, "archiving") is True

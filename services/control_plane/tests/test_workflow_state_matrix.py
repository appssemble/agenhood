"""Exhaustive terminal_action decision matrix + per-step timeline transition table.

Complements test_workflow_engine_decide.py (spot-checks of specific statuses)
by asserting coverage over the FULL task-status universe and locking
_TERMINAL_FAIL so a new failing status cannot slip in undetected.

Per-step timeline transitions (init_timeline → mark_running → mark_completed /
mark_failed) are tested as chained state sequences; individual function
behaviour + timestamp formatting is already covered by test_workflow_timeline.py
so this file focuses on the observable status progression and immutability.

NOTE on real signatures (differ from the brief's sketch):
- init_timeline(steps: list[dict])          — takes step dicts, not step_count
- mark_running(tl, i, *, started_at: datetime, container_id=None)
- mark_completed(tl, i, ended_at: datetime)  — positional ended_at
- mark_failed(tl, i, ended_at: datetime)     — positional ended_at, no error=
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane import workflow_engine as W
from control_plane import workflow_timeline as T

pytestmark = pytest.mark.unit

# ── Task-status universe ──────────────────────────────────────────────────────
# Keep in sync with the reconciler / lifecycle service.  Adding a new status
# here is the human-readable acknowledgement that the matrix must be revisited.
TASK_STATUSES = ["pending", "running", "completed", "failed", "cancelled", "timed_out"]

# ── Minimal step stubs for init_timeline (takes list[dict], not step_count) ──
_STEP_1 = [{"container_id": "con_1"}]
_STEP_2 = [{"container_id": "con_1"}, {"container_id": "con_2"}]

_NOW = datetime(2026, 6, 30, 10, 0, 0, tzinfo=UTC)


# ── Exhaustive terminal_action matrix ─────────────────────────────────────────

@pytest.mark.parametrize("status", TASK_STATUSES)
def test_terminal_action_covers_every_task_status(status: str) -> None:
    """Drive terminal_action over the full task-status universe for a non-final
    step (cursor=0, step_count=2).  The assertion logic mirrors the engine's
    branch structure exactly, so the test fails for a new status only when the
    engine's handling is non-obvious (i.e. it falls through to 'wait' but the
    intent is something else).

    'completed' → 'advance'; _TERMINAL_FAIL members → 'fail'; all others → 'wait'.
    """
    got = W.terminal_action(0, 2, status)
    if status == "completed":
        assert got == "advance"
    elif status in W._TERMINAL_FAIL:
        assert got == "fail"
    else:
        assert got == "wait"


def test_terminal_action_last_step_completes() -> None:
    """Final step (cursor == step_count - 1) + completed → 'complete', not 'advance'."""
    assert W.terminal_action(1, 2, "completed") == "complete"


def test_terminal_fail_set_is_locked() -> None:
    """Meta-gate: changing _TERMINAL_FAIL must be a deliberate edit here too.

    If this test fails, update both the set and this assertion — it ensures
    that removing or renaming a failing status is always a conscious decision.
    """
    assert W._TERMINAL_FAIL == {"failed", "cancelled", "timed_out"}


def test_unknown_status_falls_through_to_wait() -> None:
    """Any status not in the known universe returns 'wait' (the engine's
    catch-all 'pending / running / unknown' branch).  A future status that
    should instead fail or advance must be added to the universe above and
    handled explicitly in the engine.
    """
    assert W.terminal_action(0, 2, "orphaned") == "wait"
    assert W.terminal_action(0, 2, "future_status") == "wait"


def test_terminal_action_all_fail_statuses_at_last_step() -> None:
    """Fail statuses return 'fail' regardless of cursor position."""
    for status in W._TERMINAL_FAIL:
        assert W.terminal_action(1, 2, status) == "fail", f"expected 'fail' for {status!r}"


# ── Per-step timeline transition table ────────────────────────────────────────

def test_step_timeline_pending_to_running_to_completed() -> None:
    """Happy-path chain: pending → running → completed."""
    tl = T.init_timeline(_STEP_2)
    assert tl[0]["status"] == "pending"

    tl = T.mark_running(tl, 0, started_at=_NOW)
    assert tl[0]["status"] == "running"

    tl = T.mark_completed(tl, 0, _NOW)
    assert tl[0]["status"] == "completed"


def test_step_timeline_running_to_failed() -> None:
    """Failure chain: pending → running → failed."""
    tl = T.init_timeline(_STEP_1)
    tl = T.mark_running(tl, 0, started_at=_NOW)
    assert tl[0]["status"] == "running"

    tl = T.mark_failed(tl, 0, _NOW)
    assert tl[0]["status"] == "failed"


def test_timeline_helpers_are_pure() -> None:
    """mark_running must not mutate the original list (pure / copy-on-write)."""
    tl = T.init_timeline(_STEP_1)
    _ = T.mark_running(tl, 0, started_at=_NOW)
    assert tl[0]["status"] == "pending"  # original untouched


def test_step_timeline_sibling_steps_unaffected() -> None:
    """Completing step 0 must leave step 1 in its prior state."""
    tl = T.init_timeline(_STEP_2)
    tl = T.mark_running(tl, 0, started_at=_NOW)
    tl = T.mark_completed(tl, 0, _NOW)
    assert tl[1]["status"] == "pending"


def test_step_timeline_full_two_step_sequence() -> None:
    """End-to-end two-step progression: both steps reach 'completed'."""
    tl = T.init_timeline(_STEP_2)
    tl = T.mark_running(tl, 0, started_at=_NOW)
    tl = T.mark_completed(tl, 0, _NOW)
    tl = T.mark_running(tl, 1, started_at=_NOW)
    tl = T.mark_completed(tl, 1, _NOW)
    assert tl[0]["status"] == "completed"
    assert tl[1]["status"] == "completed"

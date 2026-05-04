from datetime import UTC, datetime, timedelta
import pytest
from control_plane.workflow_engine import terminal_action, is_stuck, STEP_NULL_GRACE_SECONDS

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status", ["pending", "running"])
def test_non_terminal_waits(status):
    assert terminal_action(0, 3, status) == "wait"


def test_completed_advances_when_more_steps():
    assert terminal_action(0, 3, "completed") == "advance"


def test_completed_completes_on_last_step():
    assert terminal_action(2, 3, "completed") == "complete"


@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out"])
def test_terminal_failure_fails(status):
    assert terminal_action(1, 3, status) == "fail"


def test_is_stuck_only_when_null_past_grace():
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    fresh = now - timedelta(seconds=STEP_NULL_GRACE_SECONDS - 5)
    stale = now - timedelta(seconds=STEP_NULL_GRACE_SECONDS + 5)
    assert is_stuck(None, stale, now) is True
    assert is_stuck(None, fresh, now) is False
    assert is_stuck("tsk_1", stale, now) is False   # has a task → not stuck
    assert is_stuck(None, None, now) is False        # never stamped → leave to reconciler

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit


def test_workflow_runs_has_nullable_steps_column():
    from control_plane.models_db import workflow_runs

    assert "steps" in workflow_runs.c
    assert workflow_runs.c.steps.nullable is True


_STEPS = [
    {"prompt_id": "prm_a", "container_id": "con_1", "variables": {}},
    {"prompt_id": "prm_b", "container_id": "con_2", "variables": {}},
]


def test_init_timeline_all_pending_with_containers():
    from control_plane.workflow_timeline import init_timeline

    tl = init_timeline(_STEPS)
    assert [e["status"] for e in tl] == ["pending", "pending"]
    assert [e["step_index"] for e in tl] == [0, 1]
    assert [e["container_id"] for e in tl] == ["con_1", "con_2"]
    assert all(e["task_id"] is None and e["started_at"] is None for e in tl)


def test_mark_running_sets_status_started_and_optional_container():
    from control_plane.workflow_timeline import init_timeline, mark_running

    now = datetime(2026, 6, 29, 9, 0, 0, tzinfo=UTC)
    tl = init_timeline(_STEPS)
    out = mark_running(tl, 1, started_at=now, container_id="con_override")
    assert out[1]["status"] == "running"
    assert out[1]["started_at"] == now.isoformat()
    assert out[1]["container_id"] == "con_override"
    # purity: input unchanged
    assert tl[1]["status"] == "pending"


def test_mark_task_completed_failed():
    from control_plane.workflow_timeline import (
        init_timeline, mark_task, mark_completed, mark_failed,
    )

    now = datetime(2026, 6, 29, 9, 5, 0, tzinfo=UTC)
    tl = init_timeline(_STEPS)
    tl = mark_task(tl, 0, "tsk_9")
    assert tl[0]["task_id"] == "tsk_9"
    done = mark_completed(tl, 0, now)
    assert done[0]["status"] == "completed" and done[0]["ended_at"] == now.isoformat()
    bad = mark_failed(tl, 1, now)
    assert bad[1]["status"] == "failed" and bad[1]["ended_at"] == now.isoformat()


def test_mutators_ignore_out_of_range_index():
    from control_plane.workflow_timeline import init_timeline, mark_completed

    tl = init_timeline(_STEPS)
    out = mark_completed(tl, 5, datetime(2026, 6, 29, tzinfo=UTC))
    assert [e["status"] for e in out] == ["pending", "pending"]


def test_mark_transfer_sets_summary_and_copies():
    from control_plane.workflow_timeline import init_timeline, mark_transfer

    tl = init_timeline([
        {"container_id": "con_1"}, {"container_id": "con_2"},
    ])
    out = mark_transfer(tl, 0, files=3, bytes_=1234)
    assert out[0]["transfer"] == {"files": 3, "bytes": 1234}
    assert "transfer" not in tl[0]          # pure: original untouched
    assert "transfer" not in out[1]


def test_mark_transfer_out_of_range_noop():
    from control_plane.workflow_timeline import init_timeline, mark_transfer

    tl = init_timeline([{"container_id": "con_1"}])
    assert mark_transfer(tl, 5, files=1, bytes_=1) == tl

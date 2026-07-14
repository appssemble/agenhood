"""Pure helpers for the per-step run timeline stored on ``workflow_runs.steps``.

Each entry records what ACTUALLY ran for a step, decoupled from the live
workflow definition (which may be edited mid-run). Every function is pure: it
copies the timeline and returns a NEW list, so results are safe to stage under a
row lock and write via ``_apply_run_update``. Timestamps are ISO strings so the
value round-trips through JSONB and matches ``run_view``'s stringify convention.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def init_timeline(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a fresh all-``pending`` timeline from a workflow's step list."""
    return [
        {
            "step_index": i,
            "task_id": None,
            "container_id": step.get("container_id"),
            "status": "pending",
            "started_at": None,
            "ended_at": None,
        }
        for i, step in enumerate(steps)
    ]


def _copy(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(e) for e in timeline]


def mark_running(
    timeline: list[dict[str, Any]],
    i: int,
    *,
    started_at: datetime,
    container_id: str | None = None,
) -> list[dict[str, Any]]:
    out = _copy(timeline)
    if 0 <= i < len(out):
        out[i]["status"] = "running"
        out[i]["started_at"] = started_at.isoformat()
        if container_id is not None:
            out[i]["container_id"] = container_id
    return out


def mark_task(timeline: list[dict[str, Any]], i: int, task_id: str) -> list[dict[str, Any]]:
    out = _copy(timeline)
    if 0 <= i < len(out):
        out[i]["task_id"] = task_id
    return out


def mark_completed(
    timeline: list[dict[str, Any]], i: int, ended_at: datetime
) -> list[dict[str, Any]]:
    out = _copy(timeline)
    if 0 <= i < len(out):
        out[i]["status"] = "completed"
        out[i]["ended_at"] = ended_at.isoformat()
    return out


def mark_failed(
    timeline: list[dict[str, Any]], i: int, ended_at: datetime
) -> list[dict[str, Any]]:
    out = _copy(timeline)
    if 0 <= i < len(out):
        out[i]["status"] = "failed"
        out[i]["ended_at"] = ended_at.isoformat()
    return out


def mark_transfer(
    timeline: list[dict[str, Any]], i: int, *, files: int, bytes_: int
) -> list[dict[str, Any]]:
    """Record a successful export transfer on the EXPORTING step's entry."""
    out = _copy(timeline)
    if 0 <= i < len(out):
        out[i]["transfer"] = {"files": files, "bytes": bytes_}
    return out

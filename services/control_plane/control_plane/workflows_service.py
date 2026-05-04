"""Pure helpers for the tenant workflow library (mirrors prompts_service).

Shape-only validation here; existence of referenced prompts/containers is
checked in the router against the DB.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from control_plane.errors import api_error
from control_plane.ids import new_workflow_id

MAX_WF_NAME = 120
MAX_WF_STEPS = 50


def _normalize_step(idx: int, step: Any) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise api_error(400, "validation_error", f"step {idx} must be an object", "steps")
    pid = step.get("prompt_id")
    cid = step.get("container_id")
    if not isinstance(pid, str) or not pid:
        raise api_error(400, "validation_error", f"step {idx} requires prompt_id", "steps")
    if not isinstance(cid, str) or not cid:
        raise api_error(400, "validation_error", f"step {idx} requires container_id", "steps")
    raw_vars = step.get("variables") or {}
    if not isinstance(raw_vars, dict):
        raise api_error(400, "validation_error", f"step {idx} variables must be an object", "steps")
    variables = {str(k): str(v) for k, v in raw_vars.items()}
    return {"prompt_id": pid, "container_id": cid, "variables": variables}


def validate_workflow_fields(*, name: str, description: str | None, steps: Any) -> list[dict[str, Any]]:
    n = (name or "").strip()
    if not (1 <= len(n) <= MAX_WF_NAME):
        raise api_error(400, "validation_error", f"name must be 1-{MAX_WF_NAME} chars", "name")
    if description is not None and not isinstance(description, str):
        raise api_error(400, "validation_error", "description must be a string", "description")
    if not isinstance(steps, list) or not steps:
        raise api_error(400, "validation_error", "a workflow needs at least one step", "steps")
    if len(steps) > MAX_WF_STEPS:
        raise api_error(400, "validation_error", f"too many steps (max {MAX_WF_STEPS})", "steps")
    return [_normalize_step(i, s) for i, s in enumerate(steps)]


def build_workflow_row(
    *, tenant_id: str, created_by: str | None, name: str,
    description: str | None, steps: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_workflow_id(),
        "tenant_id": tenant_id,
        "name": name.strip(),
        "description": description,
        "steps": steps,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def workflow_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "steps": list(row.get("steps") or []),
        "created_by": row.get("created_by"),
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
    }


def run_view(row: dict[str, Any]) -> dict[str, Any]:
    def _s(v: Any) -> Any:
        return str(v) if v is not None else None
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "status": row["status"],
        "cursor": row["cursor"],
        "step_count": row["step_count"],
        "current_task_id": row.get("current_task_id"),
        "error_step": row.get("error_step"),
        "error_message": row.get("error_message"),
        "trigger_source": row["trigger_source"],
        "scheduled_task_id": row.get("scheduled_task_id"),
        "started_at": _s(row.get("started_at")),
        "ended_at": _s(row.get("ended_at")),
    }


def step_view(s: dict[str, Any]) -> dict[str, Any]:
    def _s(v: Any) -> Any:
        return str(v) if v is not None else None
    return {
        "step_index": s.get("step_index"),
        "task_id": s.get("task_id"),
        "container_id": s.get("container_id"),
        "status": s.get("status"),
        "started_at": _s(s.get("started_at")),
        "ended_at": _s(s.get("ended_at")),
    }


def run_detail_view(row: dict[str, Any]) -> dict[str, Any]:
    out = run_view(row)
    steps = row.get("steps")
    out["steps"] = [step_view(s) for s in steps] if steps is not None else None
    return out

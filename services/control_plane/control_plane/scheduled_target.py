from __future__ import annotations

from typing import Any

from control_plane.errors import api_error


def validate_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise api_error(400, "validation_error", "target must be an object", "target")
    kind = target.get("kind")
    if kind == "prompt":
        cid, pid = target.get("container_id"), target.get("prompt_id")
        if not isinstance(cid, str) or not cid:
            raise api_error(400, "validation_error", "prompt target requires container_id", "target")
        if not isinstance(pid, str) or not pid:
            raise api_error(400, "validation_error", "prompt target requires prompt_id", "target")
        raw = target.get("variables") or {}
        if not isinstance(raw, dict):
            raise api_error(400, "validation_error", "variables must be an object", "target")
        return {"kind": "prompt", "container_id": cid, "prompt_id": pid,
                "variables": {str(k): str(v) for k, v in raw.items()}}
    if kind == "workflow":
        wid = target.get("workflow_id")
        if not isinstance(wid, str) or not wid:
            raise api_error(400, "validation_error", "workflow target requires workflow_id", "target")
        return {"kind": "workflow", "workflow_id": wid}
    raise api_error(400, "validation_error", "target.kind must be 'prompt' or 'workflow'", "target")

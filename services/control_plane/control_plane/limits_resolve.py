from __future__ import annotations

from typing import Any

from agentcore.errors import ValidationError
from agentcore.limits import resolve_limits
from agentcore.models import ResolvedLimits, TaskLimits
from control_plane.errors import validation_error


def resolve_task_limits(
    task_limits: TaskLimits, tenant_limits: dict[str, Any]
) -> ResolvedLimits:
    """Resolve requested task limits against the seed tenant defaults/ceilings.

    For the seed tenant (Unit 2), defaults == ceilings.  Full per-tenant
    resolution (separate defaults + ceilings) is wired in Unit 3.
    """
    defaults = ResolvedLimits(
        max_iterations=int(tenant_limits["default_max_iterations"]),
        max_tokens=int(tenant_limits["default_max_tokens"]),
        timeout_seconds=int(tenant_limits["default_task_timeout_seconds"]),
    )
    try:
        # defaults == ceilings for the seed tenant; Unit 3 will split them.
        return resolve_limits(task_limits, defaults, defaults)
    except ValidationError as exc:
        # exc.field is prefixed with "limits." (e.g. "limits.max_iterations").
        # Strip the prefix so the API error field matches the request field name.
        raw_field: str | None = exc.field
        if raw_field is not None and raw_field.startswith("limits."):
            raw_field = raw_field[len("limits."):]
        raise validation_error(str(exc), field=raw_field) from exc

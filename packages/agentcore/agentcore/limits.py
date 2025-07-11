"""Pure limit resolution (spec §4.4, §6.2).

Each ``default_*`` value is both the value applied when a task omits a limit and
the ceiling the task may not exceed. A task may request a *smaller* bound; a
request above the ceiling is rejected.
"""

from __future__ import annotations

from agentcore.errors import ValidationError
from agentcore.models import ResolvedLimits, TaskLimits


class LimitExceededError(ValidationError):
    """A requested limit exceeds the tenant ceiling (spec §6.2)."""


def _resolve_field(
    requested: int | None, default: int, ceiling: int, field: str
) -> int:
    if requested is None:
        return default
    if requested > ceiling:
        raise LimitExceededError(
            f"{field} {requested} exceeds the maximum of {ceiling}",
            field=field,
        )
    return requested


def resolve_limits(
    requested: TaskLimits,
    defaults: ResolvedLimits,
    ceilings: ResolvedLimits,
) -> ResolvedLimits:
    """Apply defaults for omitted fields; honor smaller requests; reject larger ones."""
    return ResolvedLimits(
        max_iterations=_resolve_field(
            requested.max_iterations,
            defaults.max_iterations,
            ceilings.max_iterations,
            "limits.max_iterations",
        ),
        max_tokens=_resolve_field(
            requested.max_tokens,
            defaults.max_tokens,
            ceilings.max_tokens,
            "limits.max_tokens",
        ),
        timeout_seconds=_resolve_field(
            requested.timeout_seconds,
            defaults.timeout_seconds,
            ceilings.timeout_seconds,
            "limits.timeout_seconds",
        ),
    )

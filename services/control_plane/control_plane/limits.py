"""Tenant-backed limit resolution for Unit 3 (spec §4.4, §6.2).

``resolve_limits`` wraps agentcore's pure resolver, mapping the tenant's
``default_*`` columns as both defaults and ceilings.  A task may request a
*smaller* bound; a request above the ceiling raises ``LimitExceeded``.
"""
from __future__ import annotations

from agentcore.models import AgentConfig, ResolvedLimits, TaskLimits


class LimitExceeded(Exception):
    """Requested limit exceeds the tenant ceiling (spec §6.2)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _resolve_one(requested: int | None, default: int, ceiling: int, field: str) -> int:
    """Resolve one limit: an explicit task request wins (capped at the ceiling);
    otherwise the ``default`` applies (the container override or, absent that, the
    tenant default), itself clamped to the ceiling for safety."""
    if requested is None:
        return min(default, ceiling)
    if requested > ceiling:
        raise LimitExceeded(field, f"{field} {requested} exceeds the ceiling {ceiling}")
    return requested


def resolve_limits(
    task_limits: TaskLimits,
    tenant_limits: dict,  # type: ignore[type-arg]
    config: AgentConfig | None = None,
) -> ResolvedLimits:
    """Resolve task limits against the container default and the tenant ceiling.

    Precedence per field: an explicit task request → the container config
    override (``config.max_*``) → the tenant default. The tenant ``default_*``
    column is the hard ceiling; a task request above it raises ``LimitExceeded``.
    A container override above the ceiling is clamped (it is also rejected at
    config-save time by ``validate_config``)."""

    def _default(override: int | None, tenant_default: int) -> int:
        return int(override) if override is not None else tenant_default

    ti = int(tenant_limits["default_max_iterations"])
    tt = int(tenant_limits["default_max_tokens"])
    tto = int(tenant_limits["default_task_timeout_seconds"])
    ci = config.max_iterations if config is not None else None
    ct = config.max_tokens if config is not None else None
    cto = config.timeout_seconds if config is not None else None
    return ResolvedLimits(
        max_iterations=_resolve_one(
            task_limits.max_iterations, _default(ci, ti), ti, "limits.max_iterations",
        ),
        max_tokens=_resolve_one(
            task_limits.max_tokens, _default(ct, tt), tt, "limits.max_tokens",
        ),
        timeout_seconds=_resolve_one(
            task_limits.timeout_seconds, _default(cto, tto), tto, "limits.timeout_seconds",
        ),
    )

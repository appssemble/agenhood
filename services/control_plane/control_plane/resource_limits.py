from __future__ import annotations

from control_plane.config import Settings
from control_plane.errors import validation_error

_MEM_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _parse_mem_bytes(value: str, *, field: str) -> int:
    """Parse a Docker-style memory string ("512m", "2g", or a bare byte count)."""
    s = value.strip().lower()
    if not s:
        raise validation_error(f"{field} must not be empty", field=field)
    if s[-1] in _MEM_UNITS and not s[-1].isdigit():
        digits, unit = s[:-1], s[-1]
    else:
        digits, unit = s, "b"
    if not digits.isdigit():
        raise validation_error(
            f"{field} must look like '512m' or '2g'", field=field
        )
    return int(digits) * _MEM_UNITS[unit]


def resolve_resource_limits(
    *,
    variant: str,
    requested_mem_limit: str | None,
    requested_cpus: float | None,
    settings: Settings,
    field_prefix: str = "resource_limits",
) -> tuple[str, float]:
    """Resolve the effective (mem_limit, cpus) for a container.

    Starts from the variant-tiered default (`full`/`slim`), overlays any
    explicitly requested value, and rejects (400 validation_error) an
    explicit value outside the global [min, max] bounds. Defaults are never
    bounds-checked — they are already within bounds by construction.

    ``field_prefix`` scopes the error's ``field`` to match the caller's wire
    shape: the create endpoint nests these under a ``resource_limits`` object
    (default), while the PATCH-resources endpoint has them at the top level
    of its body (pass ``field_prefix=""``).
    """
    default_mem = (
        settings.agent_mem_limit_slim if variant == "slim" else settings.agent_mem_limit_full
    )
    default_cpus = (
        settings.agent_cpus_slim if variant == "slim" else settings.agent_cpus_full
    )

    mem_limit = requested_mem_limit if requested_mem_limit is not None else default_mem
    cpus = requested_cpus if requested_cpus is not None else default_cpus

    def _field(name: str) -> str:
        return f"{field_prefix}.{name}" if field_prefix else name

    if requested_mem_limit is not None:
        mem_bytes = _parse_mem_bytes(mem_limit, field=_field("mem_limit"))
        min_bytes = _parse_mem_bytes(settings.agent_mem_limit_min, field="agent_mem_limit_min")
        max_bytes = _parse_mem_bytes(settings.agent_mem_limit_max, field="agent_mem_limit_max")
        if not (min_bytes <= mem_bytes <= max_bytes):
            raise validation_error(
                f"mem_limit must be between {settings.agent_mem_limit_min} and "
                f"{settings.agent_mem_limit_max}",
                field=_field("mem_limit"),
            )

    if requested_cpus is not None:
        if not (settings.agent_cpus_min <= cpus <= settings.agent_cpus_max):
            raise validation_error(
                f"cpus must be between {settings.agent_cpus_min} and "
                f"{settings.agent_cpus_max}",
                field=_field("cpus"),
            )

    return mem_limit, cpus

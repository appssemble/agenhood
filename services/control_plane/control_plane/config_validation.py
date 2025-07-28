from __future__ import annotations

from typing import Any

# Trigger driver + tool registration so DRIVERS is populated.
import agentcore.drivers.vanilla  # noqa: F401
import agentcore.tools  # noqa: F401
from agentcore.drivers.base import DRIVERS
from agentcore.models import AgentConfig
from control_plane.errors import APIError as APIErrorLike  # re-exported for tests  # noqa: F401
from control_plane.errors import validation_error
from control_plane.model_catalog import is_valid, load_catalog

_CATALOG_CACHE: list | None = None  # type: ignore[type-arg]


def _catalog() -> list:  # type: ignore[type-arg]
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = load_catalog()
    return _CATALOG_CACHE


_LEGAL_PROMPT_MODES = {"augment", "replace"}


# ---------------------------------------------------------------------------
# Unit 3: tenant-scoped exception + gating function
# ---------------------------------------------------------------------------


class ConfigInvalid(Exception):
    """Config is valid structurally but violates a tenant policy (spec §4.4)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def validate_config(config: AgentConfig, tenant_limits: dict[str, Any]) -> None:
    """Validate an AgentConfig against the driver registry + tenant limits.

    Raises control_plane.errors.APIError(code="validation_error") on the first failure.
    """
    # 1. Driver recognized.
    driver = DRIVERS.get(config.driver)
    if driver is None:
        raise validation_error(f"unknown driver '{config.driver}'", field="driver")

    # 2. Driver allowed for the tenant.
    allowed_drivers: list[str] = tenant_limits.get("allowed_drivers", [])
    if config.driver not in allowed_drivers:
        raise validation_error(
            f"driver '{config.driver}' not allowed for this tenant", field="driver"
        )

    # 3. Model is in the catalog and the driver can run it.
    if not is_valid(_catalog(), config.model, config.driver):
        raise validation_error(
            f"model '{config.model}' is not available for driver '{config.driver}'",
            field="model",
        )

    # 4. Prompt mode legal.
    if config.system_prompt_mode not in _LEGAL_PROMPT_MODES:
        raise validation_error(
            f"system_prompt_mode '{config.system_prompt_mode}' is not legal",
            field="system_prompt_mode",
        )

    # 5. Tools allowed/editable for the driver.
    template = driver.default_template
    if config.tools and not template.tools_user_editable:
        # Driver owns its tools; the only legal value is its default set (or empty).
        if list(config.tools) != list(template.available_tools):
            raise validation_error(
                f"driver '{config.driver}' does not allow editing tools", field="tools"
            )
    available = set(template.available_tools)
    for tool in config.tools:
        if tool not in available:
            raise validation_error(
                f"tool '{tool}' is not available for driver '{config.driver}'",
                field="tools",
            )

    # 6. Per-container limit overrides: positive and within the tenant ceiling.
    for field, value, ceiling_key in (
        ("max_iterations", config.max_iterations, "default_max_iterations"),
        ("max_tokens", config.max_tokens, "default_max_tokens"),
        ("timeout_seconds", config.timeout_seconds, "default_task_timeout_seconds"),
    ):
        if value is None:
            continue
        if value < 1:
            raise validation_error(f"{field} must be a positive integer", field=field)
        ceiling = tenant_limits.get(ceiling_key)
        if ceiling is not None and value > int(ceiling):
            raise validation_error(
                f"{field} {value} exceeds the tenant ceiling {int(ceiling)}", field=field
            )


def validate_config_against_tenant(config: AgentConfig, tenant_limits: dict[str, Any]) -> None:
    """Tenant-scoped gating layered on top of driver/tool validation (spec §4.4).

    Raises ``ConfigInvalid`` (not ``APIError``) so callers can translate to the
    appropriate HTTP code and error-code string.  Call sites should catch and
    convert:

        try:
            validate_config_against_tenant(cfg, limits)
        except ConfigInvalid as e:
            raise api_error(400, "validation_error", e.message, e.field)
    """
    allowed_drivers: list[str] = tenant_limits.get("allowed_drivers", [])
    if config.driver not in allowed_drivers:
        raise ConfigInvalid(
            "driver", f"Driver {config.driver!r} is not allowed for this tenant"
        )
    if not is_valid(_catalog(), config.model, config.driver):
        raise ConfigInvalid(
            "model", f"Model {config.model!r} is not available for driver {config.driver!r}"
        )

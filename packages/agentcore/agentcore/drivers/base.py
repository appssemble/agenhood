"""Driver Protocol, capability/template descriptors, and the driver registry.

The shim *executes* ``Driver.run``; the control plane *imports the same module*
to read ``capabilities`` / ``default_template`` for config validation and to seed
built-in template rows. One source of truth for driver metadata (index §2, §5).

Index §11 reconciliations applied:
- ``Driver.run`` includes ``workspace: str = "/workspace"`` (§11.1)
- ``DriverTemplate.supports_context`` is the canonical name (§11.2)
- ``get_driver`` helper raising ``NotFoundError`` is present (§11.3)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agentcore.errors import NotFoundError
from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimSkill,
    TaskBody,
    TaskResult,
)


@dataclass(frozen=True)
class DriverCapabilities:
    supports_tools: bool
    supports_structured_output: bool
    supports_cancel: bool
    requires_image_feature: str | None = None
    supports_mcp: bool = False
    supports_skills: bool = False


@dataclass(frozen=True)
class DriverTemplate:
    driver: str
    default_system_prompt: str
    available_tools: list[str]  # [] if the driver owns its tools
    tools_user_editable: bool
    supports_context: bool  # canonical name per index §11.2


# emit(event_type, payload) -> persists+streams one event (seq assigned by caller)
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


def _coerce_token_pair(tin: Any, tout: Any) -> tuple[int, int] | None:
    """Coerce a raw ``(input, output)`` token pair to ``(int, int)``, else None.

    Rejects bools (an int subclass — a stray True/False must not be counted) and
    any non-numeric value; casts int/float with ``int()``.
    """
    if isinstance(tin, bool) or not isinstance(tin, (int, float)):
        return None
    if isinstance(tout, bool) or not isinstance(tout, (int, float)):
        return None
    return int(tin), int(tout)


class Driver(Protocol):
    name: str
    capabilities: DriverCapabilities
    default_template: DriverTemplate

    async def run(
        self,
        *,
        task: TaskBody,
        config: AgentConfig,
        limits: ResolvedLimits,
        credential: str,
        emit: EmitFn,
        cancel: asyncio.Event,
        credential_kind: str = "api_key",
        credential_meta: dict[str, Any] | None = None,
        workspace: str = "/workspace",  # index §11.1
        skills: list[ShimSkill] | None = None,
        mcp_servers: list[Any] | None = None,
        session_id: str | None = None,
        session_is_continuation: bool = False,
        env: dict[str, str] | None = None,
    ) -> TaskResult: ...


DRIVERS: dict[str, Driver] = {}


def register(driver: Driver) -> None:
    DRIVERS[driver.name] = driver


def get_driver(name: str) -> Driver:
    """Look up a registered driver, raising ``NotFoundError`` if unknown."""
    try:
        return DRIVERS[name]
    except KeyError:
        raise NotFoundError(f"unknown driver: {name!r}", field="driver") from None

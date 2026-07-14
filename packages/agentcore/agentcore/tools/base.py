"""Tool Protocol, spec/context/result descriptors, and the tool registry (index §5).

``ToolSpec``s are the metadata the control plane reads to validate which tools a
config may enable (and to enforce ``requires_image_feature``). The shim runs
``Tool.run``. The implicit ``done`` tool is NOT in ``TOOLS`` (spec §3.6).

Index §11 reconciliation applied:
- ``get_tool`` helper raising ``NotFoundError`` is present (§11.3)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentcore.errors import NotFoundError


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for the tool's input
    requires_image_feature: str | None = None  # e.g. "chromium"


@dataclass
class ToolContext:
    workspace: str  # "/workspace"
    cancel: asyncio.Event
    # Per-container env vars merged into tool subprocess environments
    # (spec: container env vars). In-memory only; never logged.
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolResult:
    ok: bool
    content: str
    duration_ms: int


class Tool(Protocol):
    spec: ToolSpec

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.spec.name] = tool


def get_tool(name: str) -> Tool:
    """Look up a registered tool, raising ``NotFoundError`` if unknown."""
    try:
        return TOOLS[name]
    except KeyError:
        raise NotFoundError(f"unknown tool: {name!r}", field="tool") from None

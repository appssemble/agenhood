"""The driver-injected `skill` tool: lazy loading of materialized skills.

Per-run, like `done` — never in config.tools or the global TOOLS registry.
Constructed with the materialized dir and the names write_skills actually
wrote, so the prompt section and the accepted names always agree.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms


def skills_dir(workspace: str) -> str:
    """The vanilla driver's skill materialization dir (inside the reserved
    .agent-runtime tree so `files`-type results never include it)."""
    return os.path.join(workspace, ".agent-runtime", "skills")


SKILL_TOOL = ToolSpec(
    name="skill",
    description=(
        "Load a skill's full instructions by name. Call this before performing "
        "a task a listed skill covers — the one-line description is not enough."
    ),
    input_schema={
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "description": "A name from the Skills list."}
        },
    },
)


class SkillTool:
    spec = SKILL_TOOL

    def __init__(self, base_dir: str, names: list[str]) -> None:
        self._base = base_dir
        self._names = set(names)

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        name = str(input.get("name", ""))
        if name not in self._names:
            available = ", ".join(sorted(self._names)) or "(none)"
            return ToolResult(
                ok=False,
                content=f"unknown skill {name!r}; available skills: {available}",
                duration_ms=_ms(start),
            )
        path = Path(self._base) / name / "SKILL.md"
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(
                ok=False,
                content=f"could not load skill {name!r}: {e}",
                duration_ms=_ms(start),
            )
        return ToolResult(
            ok=True,
            content=f"Base directory for this skill: {self._base}/{name}\n\n{body}",
            duration_ms=_ms(start),
        )

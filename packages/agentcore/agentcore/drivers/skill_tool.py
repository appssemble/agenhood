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

DEFAULT_SKILL_CONTENT_MAX_CHARS = 100_000


def _strip_frontmatter(text: str) -> str:
    """Drop a leading frontmatter block delimited by bare ``---`` lines;
    anything malformed (no opener line, no bare closer) returns raw."""
    if not text.startswith("---\n"):
        return text
    pos = 3
    while True:
        end = text.find("\n---", pos)
        if end == -1:
            return text
        after = end + len("\n---")
        if after == len(text):
            return ""
        if text[after] == "\n":
            return text[after + 1:].lstrip("\n")
        pos = after  # matched e.g. "\n----" or "\n--- x" — keep scanning


def skills_dir(workspace: str) -> str:
    """The vanilla driver's skill materialization dir (inside the reserved
    .agent-runtime tree so `files`-type results never include it)."""
    return os.path.join(workspace, ".agent-runtime", "skills")


SKILL_TOOL = ToolSpec(
    name="skill",
    description=(
        "Load a skill's full instructions by name. When a request matches a "
        "listed skill, call this FIRST — before doing the work and before "
        "reading any files."
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
        self._served: set[str] = set()

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

        if name in self._served:
            return ToolResult(
                ok=True,
                content=f"Skill {name!r} is already loaded in this conversation.",
                duration_ms=_ms(start),
            )

        skill_dir = f"{self._base}/{name}"
        content = _strip_frontmatter(body)
        content = content.replace("${CLAUDE_SKILL_DIR}", skill_dir)

        try:
            limit = int(
                os.environ.get(
                    "SKILL_CONTENT_MAX_CHARS", DEFAULT_SKILL_CONTENT_MAX_CHARS
                )
            )
        except ValueError:
            limit = DEFAULT_SKILL_CONTENT_MAX_CHARS
        if len(content) > limit:
            dropped = len(content) - limit
            content = content[:limit] + (
                f"\n[... truncated {dropped} chars — read the rest of "
                f"{skill_dir}/SKILL.md in slices if needed]"
            )

        self._served.add(name)
        return ToolResult(
            ok=True,
            content=f"Base directory for this skill: {skill_dir}\n\n{content}",
            duration_ms=_ms(start),
        )

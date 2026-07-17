from __future__ import annotations

import json

from agentcore.models import AgentConfig, ResolvedLimits, ShimSkill, TaskBody
from agentcore.tools.base import ToolSpec

WORKSPACE_SECTION = (
    "## Workspace\n"
    "Your filesystem root for output is `/workspace`. Anything you want to "
    "persist must be under this path. The rest of the filesystem is read-only."
)

TERMINATION_SECTION = (
    "## Termination\n"
    "You must call `done` to finish: on success `{success: true, output: ...}`; "
    "if you cannot accomplish the task `{success: false, reason: ...}`. Ending "
    "your turn without calling `done` will not finish the task."
)


def assemble_system_prompt(
    *,
    config: AgentConfig,
    driver_default_system_prompt: str,
    tool_specs: list[ToolSpec],
    task: TaskBody,
    limits: ResolvedLimits,
    skills: list[ShimSkill] | None = None,
) -> str:
    """Assemble the system prompt per spec §3.7.

    `tool_specs` is the list of enabled-tool specs PLUS the always-present `done`
    spec, in the order they should appear in the inventory. The caller (the
    vanilla driver) supplies that list.
    """
    base = config.system_prompt or driver_default_system_prompt

    if config.system_prompt_mode == "replace":
        return config.system_prompt

    sections: list[str] = [base, WORKSPACE_SECTION]

    # Tool inventory — names and descriptions only. Input schemas travel in
    # the API `tools` parameter; embedding them here too doubled the per-call
    # baseline (18.6k vs 1.8k tokens with an MCP server attached).
    tool_lines = [
        "You have these tools (parameter schemas are provided via the API "
        "tools parameter):"
    ]
    for spec in tool_specs:
        tool_lines.append(f"- {spec.name}: {spec.description}")
    sections.append("## Tools\n" + "\n".join(tool_lines))

    # Skills (names + descriptions only — content loads via the `skill` tool)
    if skills:
        skill_lines = [
            "Named skills carry detailed instructions for specific kinds of "
            "work. When a request matches a skill's description, your FIRST "
            "action is to load it with the `skill` tool — do not attempt the "
            "work from the description alone, and do not search the "
            "filesystem for skill files.",
        ]
        for s in skills:
            skill_lines.append(f"- {s.name}: {s.description}")
        sections.append("## Skills\n" + "\n".join(skill_lines))

    # Output contract
    output_body = "Call `done` with `{ success, output?, reason? }`."
    if task.output.type == "structured" and task.output.json_schema is not None:
        output_body += (
            " On success, put an object matching this schema in `output`:\n"
            f"{json.dumps(task.output.json_schema)}"
        )
    sections.append("## Output\n" + output_body)

    # Termination
    sections.append(TERMINATION_SECTION)

    # Standing context
    ctx_parts: list[str] = []
    if config.context.variables:
        ctx_parts.append("variables:\n" + json.dumps(config.context.variables, indent=2))
    if config.context.text:
        ctx_parts.append(config.context.text)
    for path in config.context.files:
        ctx_parts.append(f"context file: {path}")
    if ctx_parts:
        sections.append("## Context\n" + "\n".join(ctx_parts))

    # Resource awareness
    sections.append(
        "## Resources\n"
        f"You have a budget of {limits.max_iterations} iterations and "
        f"{limits.max_tokens} tokens. Be deliberate."
    )

    return "\n\n".join(sections)

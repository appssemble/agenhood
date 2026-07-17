# packages/agentcore/tests/test_prompt.py
import json

import pytest

from agentcore.models import (
    AgentConfig,
    ContextSpec,
    OutputContract,
    ResolvedLimits,
    TaskBody,
)
from agentcore.prompt import assemble_system_prompt
from agentcore.tools.base import ToolSpec

pytestmark = pytest.mark.unit

DONE_SPEC = ToolSpec(
    name="done",
    description="Signal task completion.",
    input_schema={"type": "object", "required": ["success"]},
)
READ_SPEC = ToolSpec(
    name="read_file",
    description="Read a file.",
    input_schema={"type": "object", "required": ["path"]},
)

LIMITS = ResolvedLimits(max_iterations=30, max_tokens=1000000, timeout_seconds=1800)


def test_replace_mode_returns_system_prompt_verbatim():
    config = AgentConfig(
        driver="vanilla",
        model="claude-x",
        system_prompt="I am the whole prompt.",
        system_prompt_mode="replace",
    )
    task = TaskBody(prompt="do it")
    out = assemble_system_prompt(
        config=config,
        driver_default_system_prompt="DEFAULT",
        tool_specs=[READ_SPEC, DONE_SPEC],
        task=task,
        limits=LIMITS,
    )
    assert out == "I am the whole prompt."


def test_augment_mode_exact_string():
    config = AgentConfig(
        driver="vanilla",
        model="claude-x",
        system_prompt="You are a research assistant.",
        system_prompt_mode="augment",
        tools=["read_file"],
        context=ContextSpec(
            variables={"team": "growth"},
            text="Prefer primary sources.",
            files=[],
        ),
    )
    task = TaskBody(
        prompt="research email tools",
        output=OutputContract(type="structured", schema={"type": "object"}),
    )
    out = assemble_system_prompt(
        config=config,
        driver_default_system_prompt="DEFAULT",
        tool_specs=[READ_SPEC, DONE_SPEC],
        task=task,
        limits=LIMITS,
    )

    expected = "\n\n".join([
        "You are a research assistant.",
        "## Workspace\n"
        "Your filesystem root for output is `/workspace`. Anything you want to "
        "persist must be under this path. The rest of the filesystem is read-only.",
        "## Tools\n"
        "You have these tools (parameter schemas are provided via the API "
        "tools parameter):\n"
        "- read_file: Read a file.\n"
        "- done: Signal task completion.",
        "## Output\n"
        "Call `done` with `{ success, output?, reason? }`. On success, put an object "
        "matching this schema in `output`:\n"
        f"{json.dumps({'type': 'object'})}",
        "## Termination\n"
        "You must call `done` to finish: on success `{success: true, output: ...}`; "
        "if you cannot accomplish the task `{success: false, reason: ...}`. Ending "
        "your turn without calling `done` will not finish the task.",
        "## Context\n"
        "variables:\n"
        f"{json.dumps({'team': 'growth'}, indent=2)}\n"
        "Prefer primary sources.",
        "## Resources\n"
        "You have a budget of 30 iterations and 1000000 tokens. Be deliberate.",
    ])
    assert out == expected


def test_augment_uses_driver_default_when_no_system_prompt():
    config = AgentConfig(driver="vanilla", model="claude-x", system_prompt="")
    task = TaskBody(prompt="x")
    out = assemble_system_prompt(
        config=config,
        driver_default_system_prompt="DRIVER DEFAULT PROMPT",
        tool_specs=[DONE_SPEC],
        task=task,
        limits=LIMITS,
    )
    assert out.startswith("DRIVER DEFAULT PROMPT")


def test_tool_inventory_omits_input_schemas():
    # Input schemas already travel in the API `tools` parameter; embedding
    # them in the system prompt doubled the per-call baseline (18.6k vs 1.8k
    # tokens with an MCP server attached).
    big_schema = {
        "type": "object",
        "required": ["url"],
        "properties": {"url": {"type": "string", "description": "x" * 200}},
    }
    spec = ToolSpec(name="scrape", description="Scrape a page.", input_schema=big_schema)
    config = AgentConfig(driver="vanilla", model="claude-x", system_prompt="P")
    out = assemble_system_prompt(
        config=config,
        driver_default_system_prompt="D",
        tool_specs=[spec, DONE_SPEC],
        task=TaskBody(prompt="x"),
        limits=LIMITS,
    )
    assert "- scrape: Scrape a page." in out
    assert "input schema" not in out
    assert json.dumps(big_schema) not in out
    assert "x" * 200 not in out


def test_augment_text_output_has_no_schema_clause():
    config = AgentConfig(driver="vanilla", model="claude-x", system_prompt="P")
    task = TaskBody(prompt="x", output=OutputContract(type="text"))
    out = assemble_system_prompt(
        config=config,
        driver_default_system_prompt="D",
        tool_specs=[DONE_SPEC],
        task=task,
        limits=LIMITS,
    )
    assert "matching this schema" not in out
    assert "## Output" in out

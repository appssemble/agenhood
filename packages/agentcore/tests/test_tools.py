import asyncio

import pytest

from agentcore.errors import NotFoundError
from agentcore.tools.base import (
    TOOLS,
    ToolContext,
    ToolResult,
    ToolSpec,
    get_tool,
    register,
)


class _EchoTool:
    spec = ToolSpec(
        name="echo",
        description="Echo the input back.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    async def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content=input["text"], duration_ms=1)


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(TOOLS)
    TOOLS.clear()
    yield
    TOOLS.clear()
    TOOLS.update(saved)


def test_register_then_lookup_by_spec_name():
    tool = _EchoTool()
    register(tool)
    assert get_tool("echo") is tool
    assert "echo" in TOOLS


def test_get_unknown_tool_raises_not_found_with_field():
    with pytest.raises(NotFoundError) as exc:
        get_tool("missing")
    assert exc.value.code == "not_found"
    assert exc.value.field == "tool"


def test_registered_tool_runs_via_protocol():
    register(_EchoTool())
    ctx = ToolContext(workspace="/workspace", cancel=asyncio.Event())

    async def go() -> ToolResult:
        return await get_tool("echo").run({"text": "hi"}, ctx)

    result = asyncio.run(go())
    assert result.ok is True
    assert result.content == "hi"

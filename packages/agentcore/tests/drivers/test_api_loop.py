# packages/agentcore/tests/drivers/test_api_loop.py
import asyncio
import json

import pytest

from agentcore.drivers.api import ApiDriver
from agentcore.llm.base import LLMResponse
from agentcore.models import (
    AgentConfig,
    OutputContract,
    ResolvedLimits,
    TaskBody,
)

pytestmark = pytest.mark.unit


class ScriptedLLM:
    """Returns canned LLMResponses in order; records the calls it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, *, model, system, messages, tools, max_tokens, credential):
        self.calls.append(
            {"model": model, "system": system, "messages": list(messages),
             "tools": tools, "max_tokens": max_tokens}
        )
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(
            content=[{"type": "text", "text": "filler"}],
            tokens_in=10, tokens_out=10, stop_reason="end_turn",
        )


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


def cfg():
    return AgentConfig(driver="api", model="claude-x", system_prompt="P", tools=[])


LIMITS = ResolvedLimits(max_iterations=10, max_tokens=100000, timeout_seconds=60)

SCHEMA = {
    "type": "object",
    "required": ["food", "kcal"],
    "properties": {"food": {"type": "string"}, "kcal": {"type": "number"}},
}


def text_response(text, tin=10, tout=10):
    return LLMResponse(
        content=[{"type": "text", "text": text}],
        tokens_in=tin, tokens_out=tout, stop_reason="end_turn",
    )


async def run_driver(llm, task, **kwargs):
    events, emit = collector()
    driver = ApiDriver(llm=llm)
    result = await driver.run(
        task=task, config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace="/tmp", **kwargs,
    )
    return result, events


@pytest.mark.asyncio
async def test_text_task_single_call_returns_text():
    llm = ScriptedLLM([text_response("The answer is 42.")])
    result, events = await run_driver(llm, TaskBody(prompt="answer?"))
    assert result.success
    assert result.output == {"success": True, "output": "The answer is 42."}
    assert len(llm.calls) == 1
    assert llm.calls[0]["tools"] == []
    types = [t for t, _ in events]
    assert types[0] == "task_started"
    assert "iteration_started" in types
    assert "assistant_message" in types
    assert "token_update" in types
    assert types[-1] == "status_change"
    assert events[-1][1]["to"] == "completed"


@pytest.mark.asyncio
async def test_structured_task_valid_json_first_try():
    llm = ScriptedLLM([text_response('{"food": "paine cu pate", "kcal": 250}')])
    task = TaskBody(prompt="x", output=OutputContract(type="structured", schema=SCHEMA))
    result, _ = await run_driver(llm, task)
    assert result.success
    assert result.output == {
        "success": True, "output": {"food": "paine cu pate", "kcal": 250},
    }
    # system prompt carries the schema and the JSON-only instruction
    assert "JSON" in llm.calls[0]["system"]
    assert '"kcal"' in llm.calls[0]["system"]


@pytest.mark.asyncio
async def test_structured_strips_code_fences():
    llm = ScriptedLLM([text_response('```json\n{"food": "x", "kcal": 1}\n```')])
    task = TaskBody(prompt="x", output=OutputContract(type="structured", schema=SCHEMA))
    result, _ = await run_driver(llm, task)
    assert result.success
    assert result.output["output"] == {"food": "x", "kcal": 1}


@pytest.mark.asyncio
async def test_structured_invalid_then_valid_feeds_error_back():
    llm = ScriptedLLM([
        text_response('{"food": "x"}'),  # missing kcal → schema error
        text_response('{"food": "x", "kcal": 9}'),
    ])
    task = TaskBody(prompt="x", output=OutputContract(type="structured", schema=SCHEMA))
    result, _ = await run_driver(llm, task)
    assert result.success
    assert result.output["output"]["kcal"] == 9
    assert len(llm.calls) == 2
    # the retry message carries the validation error
    retry_msgs = llm.calls[1]["messages"]
    assert any(
        m["role"] == "user" and "kcal" in str(m["content"]) for m in retry_msgs
    )


@pytest.mark.asyncio
async def test_structured_retry_exhaustion_fails():
    llm = ScriptedLLM([
        text_response("not json at all"),
        text_response("still not json"),
        text_response("nope"),
    ])
    task = TaskBody(prompt="x", output=OutputContract(type="structured", schema=SCHEMA))
    result, events = await run_driver(llm, task)
    assert not result.success
    assert result.reason == "invalid_structured_output"
    assert len(llm.calls) == 3  # MAX 3 total calls
    assert events[-1][1]["to"] == "failed"


@pytest.mark.asyncio
async def test_cancel_before_call():
    llm = ScriptedLLM([])
    events, emit = collector()
    cancel = asyncio.Event()
    cancel.set()
    result = await ApiDriver(llm=llm).run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=cancel, workspace="/tmp",
    )
    assert not result.success
    assert result.reason == "cancelled"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_unroutable_model_fails():
    class NoRoute:
        def route(self, model):
            raise ValueError("no route")

    events, emit = collector()
    result = await ApiDriver(router=NoRoute()).run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace="/tmp",
    )
    assert not result.success
    assert result.reason == "unroutable_model"


@pytest.mark.asyncio
async def test_api_error_fails_with_message():
    class Boom:
        async def create(self, **kwargs):
            raise RuntimeError("provider exploded")

    events, emit = collector()
    result = await ApiDriver(llm=Boom()).run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace="/tmp",
    )
    assert not result.success
    assert result.reason == "api_error"
    terminal = [p for t, p in events if t == "status_change"][-1]
    assert "provider exploded" in terminal["error"]["message"]


@pytest.mark.asyncio
async def test_session_continuation_appends_history(tmp_path):
    ws = str(tmp_path)
    llm1 = ScriptedLLM([text_response("first answer")])
    events, emit = collector()
    r1 = await ApiDriver(llm=llm1).run(
        task=TaskBody(prompt="first q"), config=cfg(), limits=LIMITS,
        credential="k", emit=emit, cancel=asyncio.Event(), workspace=ws,
        session_id="s1", session_is_continuation=False,
    )
    assert r1.success
    llm2 = ScriptedLLM([text_response("second answer")])
    r2 = await ApiDriver(llm=llm2).run(
        task=TaskBody(prompt="second q"), config=cfg(), limits=LIMITS,
        credential="k", emit=emit, cancel=asyncio.Event(), workspace=ws,
        session_id="s1", session_is_continuation=True,
    )
    assert r2.success
    sent = llm2.calls[0]["messages"]
    assert any("first q" in str(m.get("content")) for m in sent)
    assert any("second q" in str(m.get("content")) for m in sent)


@pytest.mark.asyncio
async def test_session_continuation_missing_state_fails(tmp_path):
    events, emit = collector()
    result = await ApiDriver(llm=ScriptedLLM([])).run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS, credential="k",
        emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
        session_id="ghost", session_is_continuation=True,
    )
    assert not result.success
    assert result.reason == "session_state_lost"


def test_capabilities_and_template():
    d = ApiDriver(llm=ScriptedLLM([]))
    assert d.name == "api"
    assert d.capabilities.supports_tools is False
    assert d.capabilities.supports_structured_output is True
    assert d.capabilities.supports_cancel is True
    assert d.capabilities.supports_mcp is False
    assert d.capabilities.supports_skills is False
    assert d.default_template.available_tools == []
    assert d.default_template.tools_user_editable is False


def test_api_driver_self_registers():
    import agentcore.drivers  # noqa: F401  (package import triggers registration)
    from agentcore.drivers.base import DRIVERS
    assert "api" in DRIVERS

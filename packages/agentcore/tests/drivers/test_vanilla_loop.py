import asyncio

import pytest

from agentcore.drivers.vanilla import VanillaDriver
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
        # Default: never-ending text turns (used for limit tests).
        return LLMResponse(
            content=[{"type": "text", "text": "thinking"}],
            tokens_in=10, tokens_out=10, stop_reason="end_turn",
        )


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


def cfg(tools=None):
    return AgentConfig(
        driver="vanilla", model="claude-x",
        system_prompt="P", tools=tools or [],
    )


LIMITS = ResolvedLimits(max_iterations=10, max_tokens=100000, timeout_seconds=60)


@pytest.mark.asyncio
async def test_tool_call_then_result_then_done_event_order():
    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "tu1", "name": "write_file",
                      "input": {"path": "a.txt", "content": "hi"}}],
            tokens_in=5, tokens_out=5, stop_reason="tool_use",
        ),
        LLMResponse(
            content=[{"type": "tool_use", "id": "tu2", "name": "done",
                      "input": {"success": True, "output": "wrote it"}}],
            tokens_in=5, tokens_out=5, stop_reason="tool_use",
        ),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="write a file", output=OutputContract(type="text"))

    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(["write_file"]), limits=LIMITS,
            credential="sk", emit=emit, cancel=asyncio.Event(),
            workspace=ws,
        )

    assert result.success
    assert result.output == {"success": True, "output": "wrote it"}
    types = [t for t, _ in events]
    assert types[0] == "task_started"
    assert "iteration_started" in types
    assert "assistant_message" in types
    assert "token_update" in types
    # token_update is emitted before assistant_message within an iteration (plan §Task 8)
    assert types.index("token_update") < types.index("assistant_message")
    # tool_call before its tool_result
    assert types.index("tool_call") < types.index("tool_result")
    assert types[-1] == "status_change"
    assert events[-1][1]["to"] == "completed"


@pytest.mark.asyncio
async def test_no_tool_use_nudges_then_continues():
    llm = ScriptedLLM([
        LLMResponse(content=[{"type": "text", "text": "I think the answer is..."}],
                    tokens_in=5, tokens_out=5, stop_reason="end_turn"),
        LLMResponse(content=[{"type": "tool_use", "id": "d", "name": "done",
                              "input": {"success": True, "output": "ok"}}],
                    tokens_in=5, tokens_out=5, stop_reason="tool_use"),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x", output=OutputContract(type="text"))
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=LIMITS, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert result.success
    # The nudge user-message should have been added: second LLM call sees 3 messages.
    assert len(llm.calls[1]["messages"]) == 3


@pytest.mark.asyncio
async def test_invalid_structured_output_keeps_loop_going():
    schema = {"type": "object", "required": ["name"],
              "properties": {"name": {"type": "string"}}}
    llm = ScriptedLLM([
        LLMResponse(content=[{"type": "tool_use", "id": "d1", "name": "done",
                              "input": {"success": True, "output": {"wrong": 1}}}],
                    tokens_in=5, tokens_out=5, stop_reason="tool_use"),
        LLMResponse(content=[{"type": "tool_use", "id": "d2", "name": "done",
                              "input": {"success": True, "output": {"name": "ok"}}}],
                    tokens_in=5, tokens_out=5, stop_reason="tool_use"),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x", output=OutputContract(type="structured", schema=schema))
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=LIMITS, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert result.success
    assert result.output == {"success": True, "output": {"name": "ok"}}
    # two done tool_results: first rejected, second accepted
    tr = [p for t, p in events if t == "tool_result" and p["tool_use_id"].startswith("d")]
    assert tr[0]["ok"] is False
    assert tr[1]["ok"] is True


@pytest.mark.asyncio
async def test_iteration_limit_fails_with_code():
    llm = ScriptedLLM([])  # always returns no-tool-use text → never finishes
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x")
    limits = ResolvedLimits(max_iterations=3, max_tokens=10**9, timeout_seconds=60)
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=limits, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert not result.success
    assert result.reason == "iteration_limit"
    sc = events[-1][1]
    assert sc["to"] == "failed"
    assert sc["error"]["code"] == "iteration_limit"
    # a warn log precedes the final status_change
    assert events[-2][0] == "log"
    assert events[-2][1]["level"] == "warn"


@pytest.mark.asyncio
async def test_token_budget_exhausted_fails_with_code():
    llm = ScriptedLLM([])  # default response burns 20 tokens/iter
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x")
    limits = ResolvedLimits(max_iterations=10**6, max_tokens=25, timeout_seconds=60)
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=limits, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert not result.success
    assert result.reason == "token_budget_exhausted"
    assert events[-1][1]["error"]["code"] == "token_budget_exhausted"


@pytest.mark.asyncio
async def test_timeout_times_out_with_code():
    class SlowLLM:
        async def create(self, **kwargs):
            await asyncio.sleep(0.05)
            return LLMResponse(content=[{"type": "text", "text": "x"}],
                               tokens_in=1, tokens_out=1, stop_reason="end_turn")
    events, emit = collector()
    driver = VanillaDriver(llm=SlowLLM())
    task = TaskBody(prompt="x")
    limits = ResolvedLimits(max_iterations=10**6, max_tokens=10**9, timeout_seconds=0)
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=limits, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert not result.success
    assert result.reason == "timeout"
    sc = events[-1][1]
    assert sc["to"] == "timed_out"
    assert sc["error"]["code"] == "timeout"


@pytest.mark.asyncio
async def test_cancellation_stops_promptly():
    cancel = asyncio.Event()
    cancel.set()  # already cancelled before the loop starts
    llm = ScriptedLLM([])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x")
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=LIMITS, credential="sk",
            emit=emit, cancel=cancel, workspace=ws,
        )
    assert not result.success
    assert result.reason == "cancelled"
    assert events[-1][1]["to"] == "cancelled"
    # No LLM call happened because we were cancelled up front.
    assert llm.calls == []


@pytest.mark.asyncio
async def test_done_with_success_false_fails_task():
    """done(success=False) must terminate the task as 'failed', not 'completed'."""
    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "df1", "name": "done",
                      "input": {"success": False, "reason": "cannot comply"}}],
            tokens_in=5, tokens_out=5, stop_reason="tool_use",
        ),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="do something risky", output=OutputContract(type="text"))
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=LIMITS, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert not result.success
    assert result.reason == "cannot comply"
    sc = events[-1][1]
    assert sc["to"] == "failed"
    assert sc["result"] == {"success": False, "reason": "cannot comply"}


@pytest.mark.asyncio
async def test_done_with_success_false_no_reason_uses_default_code():
    """done(success=False) with no reason uses 'model_reported_failure' as code."""
    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "df2", "name": "done",
                      "input": {"success": False}}],
            tokens_in=5, tokens_out=5, stop_reason="tool_use",
        ),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    task = TaskBody(prompt="x", output=OutputContract(type="text"))
    import tempfile
    with tempfile.TemporaryDirectory() as ws:
        result = await driver.run(
            task=task, config=cfg(), limits=LIMITS, credential="sk",
            emit=emit, cancel=asyncio.Event(), workspace=ws,
        )
    assert not result.success
    assert result.reason == "model_reported_failure"
    assert events[-1][1]["to"] == "failed"


def test_vanilla_self_registers():
    import agentcore.drivers.vanilla  # noqa: F401
    from agentcore.drivers.base import DRIVERS
    assert "vanilla" in DRIVERS


def test_vanilla_capabilities_and_template():
    import agentcore.drivers.vanilla  # noqa: F401
    from agentcore.drivers.base import DRIVERS
    d = DRIVERS["vanilla"]
    assert d.capabilities.supports_tools is True
    assert d.capabilities.supports_structured_output is True
    assert d.capabilities.supports_cancel is True
    assert d.capabilities.requires_image_feature is None
    assert d.default_template.driver == "vanilla"
    assert d.default_template.tools_user_editable is True


@pytest.mark.asyncio
async def test_vanilla_session_first_turn_writes_state_file(tmp_path):
    from agentcore.drivers.session_state import read_session_state
    from agentcore.drivers.vanilla import VanillaDriver
    from agentcore.llm.base import LLMResponse

    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "tu1", "name": "done",
                      "input": {"success": True, "output": "done"}}],
            tokens_in=5, tokens_out=2, stop_reason="tool_use",
        ),
    ])
    driver = VanillaDriver(llm=llm)
    events, emit = collector()
    cancel = asyncio.Event()

    result = await driver.run(
        task=TaskBody(prompt="hello"),
        config=AgentConfig(driver="vanilla", model="m-test"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100_000, timeout_seconds=30),
        credential="cred", emit=emit, cancel=cancel,
        workspace=str(tmp_path), session_id="sess-1", session_is_continuation=False,
    )

    assert result.success is True
    state = read_session_state(str(tmp_path), "vanilla", "sess-1")
    assert state is not None
    assert state["messages"][0] == {"role": "user", "content": "hello"}


@pytest.mark.asyncio
async def test_vanilla_session_continuation_seeds_prior_messages(tmp_path):
    from agentcore.drivers.session_state import write_session_state
    from agentcore.drivers.vanilla import VanillaDriver
    from agentcore.llm.base import LLMResponse

    prior = [
        {"role": "user", "content": "what is 2+2"},
        {"role": "assistant", "content": [{"type": "text", "text": "4"}]},
    ]
    write_session_state(str(tmp_path), "vanilla", "sess-2", {"messages": prior})

    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "tu1", "name": "done",
                      "input": {"success": True, "output": "done"}}],
            tokens_in=5, tokens_out=2, stop_reason="tool_use",
        ),
    ])
    driver = VanillaDriver(llm=llm)
    events, emit = collector()
    cancel = asyncio.Event()

    await driver.run(
        task=TaskBody(prompt="and 3+3?"),
        config=AgentConfig(driver="vanilla", model="m-test"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100_000, timeout_seconds=30),
        credential="cred", emit=emit, cancel=cancel,
        workspace=str(tmp_path), session_id="sess-2", session_is_continuation=True,
    )

    # The LLM's first call must have seen the full prior transcript + new prompt.
    sent = llm.calls[0]["messages"]
    assert sent[0] == prior[0]
    assert sent[1] == prior[1]
    assert sent[2] == {"role": "user", "content": "and 3+3?"}


@pytest.mark.asyncio
async def test_vanilla_session_missing_state_fails_fast(tmp_path):
    from agentcore.drivers.vanilla import VanillaDriver
    from agentcore.llm.base import LLMResponse

    llm = ScriptedLLM([LLMResponse(content=[], tokens_in=0, tokens_out=0, stop_reason="end_turn")])
    driver = VanillaDriver(llm=llm)
    events, emit = collector()
    cancel = asyncio.Event()

    result = await driver.run(
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="m-test"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100_000, timeout_seconds=30),
        credential="cred", emit=emit, cancel=cancel,
        workspace=str(tmp_path), session_id="sess-missing", session_is_continuation=True,
    )

    assert result.success is False
    assert result.reason == "session_state_lost"
    assert llm.calls == []  # the LLM must never be called
    assert ("status_change", {"from": "running", "to": "failed", "result": None,
             "error": {"code": "session_state_lost", "message": "session state file missing"}}) in events


@pytest.mark.asyncio
async def test_vanilla_no_session_id_unchanged(tmp_path):
    """Omitting session_id must behave exactly like today: no state file written."""
    import os

    from agentcore.drivers.vanilla import VanillaDriver
    from agentcore.llm.base import LLMResponse

    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "tu1", "name": "done",
                      "input": {"success": True, "output": "done"}}],
            tokens_in=5, tokens_out=2, stop_reason="tool_use",
        ),
    ])
    driver = VanillaDriver(llm=llm)
    events, emit = collector()
    cancel = asyncio.Event()

    result = await driver.run(
        task=TaskBody(prompt="hello"),
        config=AgentConfig(driver="vanilla", model="m-test"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100_000, timeout_seconds=30),
        credential="cred", emit=emit, cancel=cancel, workspace=str(tmp_path),
    )

    assert result.success is True
    assert not os.path.isdir(os.path.join(str(tmp_path), ".agent-state", "vanilla", "sessions"))


@pytest.mark.asyncio
async def test_router_selects_client_and_wire_model(tmp_path):
    """With a router, the driver calls the routed client with the wire id."""
    from agentcore.llm.base import LLMResponse as LR

    done = LR(content=[{"type": "tool_use", "id": "d", "name": "done",
                        "input": {"success": True, "output": "ok"}}],
              tokens_in=1, tokens_out=1, stop_reason="tool_use")
    routed = ScriptedLLM([done])
    unused = ScriptedLLM([])

    class FakeRouter:
        def route(self, model):
            assert model == "opencode-go/glm-5.2"
            return routed, "glm-5.2"

    driver = VanillaDriver(llm=unused, router=FakeRouter())
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="x"),
        config=AgentConfig(driver="vanilla", model="opencode-go/glm-5.2"),
        limits=LIMITS, credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )
    assert result.success
    assert unused.calls == []              # fallback client never used
    assert routed.calls[0]["model"] == "glm-5.2"  # wire id, not catalog id


@pytest.mark.asyncio
async def test_unroutable_model_fails_task(tmp_path):
    from agentcore.llm.router import LLMRouter

    driver = VanillaDriver(router=LLMRouter())
    events, emit = collector()
    result = await driver.run(
        task=TaskBody(prompt="x"),
        config=AgentConfig(driver="vanilla", model="gemini-3.5-flash"),
        limits=LIMITS, credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
    )
    assert not result.success
    assert result.reason == "unroutable_model"
    assert events[-1][1]["to"] == "failed"
    assert events[-1][1]["error"]["code"] == "unroutable_model"


@pytest.mark.asyncio
async def test_full_loop_over_openai_wire(tmp_path):
    """End-to-end: real router + real OpenAICompatClient + respx chat
    completions backend, through tool execution to done."""
    import httpx
    import respx

    from agentcore.llm.router import LLMRouter

    def _oa(message, finish):
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "model": "gpt-x",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    responses = iter([
        _oa({"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "write_file",
                          "arguments": "{\"path\": \"a.txt\", \"content\": \"hi\"}"}},
        ]}, "tool_calls"),
        _oa({"role": "assistant", "content": None, "tool_calls": [
            {"id": "c2", "type": "function",
             "function": {"name": "done",
                          "arguments": "{\"success\": true, \"output\": \"wrote\"}"}},
        ]}, "tool_calls"),
    ])

    with respx.mock:
        respx.post("http://oa.stub/v1/chat/completions").mock(
            side_effect=lambda request: next(responses)
        )
        driver = VanillaDriver(router=LLMRouter(openai_base_url="http://oa.stub/v1"))
        events, emit = collector()
        result = await driver.run(
            task=TaskBody(prompt="write a file", output=OutputContract(type="text")),
            config=AgentConfig(driver="vanilla", model="gpt-5.2",
                               tools=["write_file"]),
            limits=LIMITS, credential="sk", emit=emit, cancel=asyncio.Event(),
            workspace=str(tmp_path),
        )

    assert result.success
    assert result.output == {"success": True, "output": "wrote"}
    assert (tmp_path / "a.txt").read_text() == "hi"
    assert events[-1][1]["to"] == "completed"

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
    assert (
        "status_change",
        {
            "from": "running",
            "to": "failed",
            "result": None,
            "error": {"code": "session_state_lost", "message": "session state file missing"},
        },
    ) in events


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


def _skill(name="pdf-reports", description="Branded PDFs", body="Use helper.py"):
    from agentcore.models import ShimSkill
    return ShimSkill(name=name, description=description, body=body)


def _done_response(output="ok"):
    from agentcore.llm.base import LLMResponse
    return LLMResponse(
        content=[{"type": "tool_use", "id": "d", "name": "done",
                  "input": {"success": True, "output": output}}],
        tokens_in=1, tokens_out=1, stop_reason="tool_use",
    )


@pytest.mark.asyncio
async def test_skills_materialized_prompted_and_loadable(tmp_path):
    from agentcore.llm.base import LLMResponse

    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "s1", "name": "skill",
                      "input": {"name": "pdf-reports"}}],
            tokens_in=1, tokens_out=1, stop_reason="tool_use",
        ),
        _done_response(),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    result = await driver.run(
        task=TaskBody(prompt="make a report"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), skills=[_skill()],
    )
    assert result.success
    # Materialized on disk.
    assert (tmp_path / ".agent-runtime" / "skills" / "pdf-reports" / "SKILL.md").exists()
    # Prompt carries the section and the skill tool spec went to the LLM.
    assert "## Skills" in llm.calls[0]["system"]
    assert any(t["name"] == "skill" for t in llm.calls[0]["tools"])
    # The skill tool returned the body.
    skill_results = [p for t, p in events if t == "tool_result" and p["tool_use_id"] == "s1"]
    assert skill_results and skill_results[0]["ok"]
    assert "Use helper.py" in skill_results[0]["content"]


@pytest.mark.asyncio
async def test_no_skills_no_skill_tool(tmp_path):
    llm = ScriptedLLM([_done_response()])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )
    assert all(t["name"] != "skill" for t in llm.calls[0]["tools"])
    assert "## Skills" not in llm.calls[0]["system"]


@pytest.mark.asyncio
async def test_invalid_skill_skipped_with_warn(tmp_path):
    llm = ScriptedLLM([_done_response()])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    result = await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path),
        skills=[_skill(name="Bad Name!")],  # fails valid_skill_name -> skipped
    )
    assert result.success  # task never aborts on skill failure
    warns = [p for t, p in events if t == "log" and p["level"] == "warn"]
    assert any("Bad Name!" in str(p.get("data", {})) for p in warns)
    assert all(t["name"] != "skill" for t in llm.calls[0]["tools"])


@pytest.mark.asyncio
async def test_tool_result_capped_with_marker(tmp_path, monkeypatch):
    from agentcore.llm.base import LLMResponse

    monkeypatch.setenv("TOOL_RESULT_MAX_CHARS", "200")
    big = tmp_path / "big.txt"
    big.write_text("x" * 5000)
    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "r1", "name": "read_file",
                      "input": {"path": "big.txt"}}],
            tokens_in=1, tokens_out=1, stop_reason="tool_use",
        ),
        _done_response(),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    result = await driver.run(
        task=TaskBody(prompt="x"), config=cfg(["read_file"]), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )
    assert result.success
    tr = [p for t, p in events if t == "tool_result" and p["tool_use_id"] == "r1"][0]
    assert len(tr["content"]) < 400
    assert "truncated" in tr["content"]
    # History got the capped version too.
    sent = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert "truncated" in sent and len(sent) < 400


@pytest.mark.asyncio
async def test_tool_exception_becomes_error_result(tmp_path):
    from agentcore.llm.base import LLMResponse
    from agentcore.tools.base import ToolSpec

    class BoomTool:
        spec = ToolSpec(name="write_file", description="d", input_schema={})
        async def run(self, input, ctx):
            raise RuntimeError("kaboom")

    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "b1", "name": "write_file",
                      "input": {}}],
            tokens_in=1, tokens_out=1, stop_reason="tool_use",
        ),
        _done_response(),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm)
    import agentcore.tools.base as tb
    original = tb.TOOLS.get("write_file")
    tb.TOOLS["write_file"] = BoomTool()
    try:
        result = await driver.run(
            task=TaskBody(prompt="x"), config=cfg(["write_file"]), limits=LIMITS,
            credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
        )
    finally:
        if original is not None:
            tb.TOOLS["write_file"] = original
    assert result.success  # loop survived the crash; model recovered via done
    tr = [p for t, p in events if t == "tool_result" and p["tool_use_id"] == "b1"][0]
    assert tr["ok"] is False
    assert "kaboom" in tr["content"]


class FakeMcpRuntime:
    """Stands in for McpRuntime: one echo adapter, records lifecycle."""

    def __init__(self, fail_server: str | None = None):
        self.errors = {}
        self.skipped_tools = []
        self.connected_with = None
        self.closed = False
        self._fail_server = fail_server

    async def connect(self, servers):
        self.connected_with = [s.name for s in servers]
        if self._fail_server:
            self.errors[self._fail_server] = "connection refused"

    def tools(self):
        from agentcore.tools.base import ToolResult, ToolSpec

        rt = self

        class EchoAdapter:
            spec = ToolSpec(
                name="mcp__stub__echo", description="[stub] echo",
                input_schema={"type": "object"},
            )
            async def run(self, input, ctx):
                return ToolResult(ok=True, content=f"echo:{input.get('text', '')}",
                                  duration_ms=1)
        return [] if rt._fail_server == "stub" else [EchoAdapter()]

    async def close(self):
        self.closed = True


def _mcp_server(name="stub"):
    from agentcore.models import ShimMcpServer
    return ShimMcpServer(name=name, url="http://stub/mcp", auth_type="none")


@pytest.mark.asyncio
async def test_mcp_tools_join_the_loop_and_runtime_closes(tmp_path):
    from agentcore.llm.base import LLMResponse

    fake = FakeMcpRuntime()
    llm = ScriptedLLM([
        LLMResponse(
            content=[{"type": "tool_use", "id": "m1", "name": "mcp__stub__echo",
                      "input": {"text": "hi"}}],
            tokens_in=1, tokens_out=1, stop_reason="tool_use",
        ),
        _done_response(),
    ])
    events, emit = collector()
    driver = VanillaDriver(llm=llm, mcp_factory=lambda: fake)
    result = await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), mcp_servers=[_mcp_server()],
    )
    assert result.success
    assert fake.connected_with == ["stub"]
    assert fake.closed  # closed on the terminal path
    assert any(t["name"] == "mcp__stub__echo" for t in llm.calls[0]["tools"])
    tr = [p for t, p in events if t == "tool_result" and p["tool_use_id"] == "m1"][0]
    assert tr["ok"] and tr["content"] == "echo:hi"
    # MCP tools never appear in the prompt text beyond the generic inventory.
    assert "mcp__stub__echo" in llm.calls[0]["system"]  # tool inventory line only


@pytest.mark.asyncio
async def test_mcp_connect_failure_warns_and_task_continues(tmp_path):
    fake = FakeMcpRuntime(fail_server="stub")
    llm = ScriptedLLM([_done_response()])
    events, emit = collector()
    driver = VanillaDriver(llm=llm, mcp_factory=lambda: fake)
    result = await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), mcp_servers=[_mcp_server()],
    )
    assert result.success
    warns = [p for t, p in events if t == "log" and p["level"] == "warn"]
    assert any("stub" in str(p.get("data", {})) for p in warns)
    assert fake.closed


@pytest.mark.asyncio
async def test_mcp_closed_even_on_budget_failure(tmp_path):
    fake = FakeMcpRuntime()
    llm = ScriptedLLM([])  # endless text turns
    events, emit = collector()
    driver = VanillaDriver(llm=llm, mcp_factory=lambda: fake)
    limits = ResolvedLimits(max_iterations=2, max_tokens=10**9, timeout_seconds=60)
    result = await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=limits,
        credential="sk", emit=emit, cancel=asyncio.Event(),
        workspace=str(tmp_path), mcp_servers=[_mcp_server()],
    )
    assert not result.success
    assert fake.closed


@pytest.mark.asyncio
async def test_no_mcp_servers_no_runtime(tmp_path):
    created = []
    def factory():
        created.append(1)
        return FakeMcpRuntime()
    llm = ScriptedLLM([_done_response()])
    events, emit = collector()
    driver = VanillaDriver(llm=llm, mcp_factory=factory)
    await driver.run(
        task=TaskBody(prompt="x"), config=cfg(), limits=LIMITS,
        credential="sk", emit=emit, cancel=asyncio.Event(), workspace=str(tmp_path),
    )
    assert created == []

import asyncio
import json

import pytest

from agentcore.drivers.codex_appserver import AppServerError
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody

pytestmark = pytest.mark.unit

LIMITS = ResolvedLimits(max_iterations=10, max_tokens=100000, timeout_seconds=60)


def cfg(model="gpt-5-codex"):
    return AgentConfig(driver="codex", model=model, system_prompt="P", tools=[])


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


class FakeAppServer:
    """Stands in for AppServerClient: records requests, replays scripted messages."""

    def __init__(self, messages=(), *, thread_id="thr_1", fail=None):
        self.requests = []
        self.messages = list(messages)
        self.thread_id = thread_id
        self.fail = dict(fail or {})
        self.alive = True
        self.terminated = False
        self.closed = False

    async def request(self, method, params, timeout=None):  # noqa: ASYNC109
        self.requests.append((method, params))
        if method in self.fail:
            raise AppServerError(f"{method}: {self.fail[method]}")
        if method == "thread/start":
            return {"thread": {"id": self.thread_id}}
        return {}

    async def next_message(self, timeout):  # noqa: ASYNC109
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(0)
        return None

    def terminate(self):
        self.terminated = True
        self.alive = False

    def abort(self):
        self.terminate()

    async def close(self, timeout=5.0):  # noqa: ASYNC109
        self.closed = True
        self.alive = False

    def params(self, method):
        return [p for m, p in self.requests if m == method]

    def methods(self):
        return [m for m, _ in self.requests]


def patch_servers(monkeypatch, servers):
    """Each app-server start takes the next FakeAppServer; records the start args."""
    starts = []

    async def fake_start(cmd, *, cwd, env):
        server = servers.pop(0)
        starts.append({"cmd": cmd, "cwd": cwd, "env": env})
        return server

    monkeypatch.setattr("agentcore.drivers.codex.start_app_server", fake_start)
    return starts


def note(method, **params):
    return {"method": method, "params": params}


def agent_message(text, item_id=None):
    return note("item/completed", item={"type": "agentMessage",
                                        "id": item_id or f"msg_{len(text)}_{text[:8]}",
                                        "text": text})


def usage(inp, out):
    return note("thread/tokenUsage/updated",
                tokenUsage={"last": {"inputTokens": inp, "outputTokens": out}})


def turn_completed(status="completed", error=None):
    return note("turn/completed", turn={"status": status, "error": error})


def answer(*texts):
    return [note("turn/started"), *[agent_message(t) for t in texts], turn_completed()]


async def run(task=None, config=None, *, tmp_path, limits=LIMITS, cancel=None, **kwargs):
    from agentcore.drivers.codex import CodexDriver

    events, emit = collector()
    result = await CodexDriver().run(
        task=task or TaskBody(prompt="do it"), config=config or cfg(), limits=limits,
        credential=kwargs.pop("credential", "sk"), emit=emit,
        cancel=cancel or asyncio.Event(), workspace=str(tmp_path), **kwargs,
    )
    return result, events


@pytest.mark.asyncio
async def test_success_emits_result_and_tokens(monkeypatch, tmp_path):
    server = FakeAppServer([note("turn/started"), agent_message("all done"), usage(100, 20),
                            turn_completed()])
    patch_servers(monkeypatch, [server])

    result, events = await run(tmp_path=tmp_path)

    assert result.success
    assert result.output == "all done"
    assert server.params("turn/start")[0]["input"] == [{"type": "text", "text": "do it"}]
    types = [t for t, _ in events]
    assert types[0] == "status_change"
    assert "codex_event" in types
    tok = [p for t, p in events if t == "token_update"][-1]
    assert tok == {"tokens_in": 100, "tokens_out": 20}
    assert events[-1][1]["to"] == "completed"
    assert server.closed


@pytest.mark.asyncio
async def test_codex_events_keep_the_exec_shape(monkeypatch, tmp_path):
    patch_servers(monkeypatch, [FakeAppServer(answer("hi"))])

    _, events = await run(tmp_path=tmp_path)

    raws = [p["raw"] for t, p in events if t == "codex_event"]
    assert [r["type"] for r in raws] == [
        "thread.started", "turn.started", "item.completed", "turn.completed"]
    assert raws[0] == {"type": "thread.started", "thread_id": "thr_1"}
    assert raws[2]["item"] == {"id": "item_0", "type": "agent_message", "text": "hi"}


@pytest.mark.asyncio
async def test_turn_failed_fails_with_the_codex_message(monkeypatch, tmp_path):
    server = FakeAppServer([note("turn/started"),
                            note("error", error={"message": "model exploded"}),
                            turn_completed("failed", {"message": "model exploded"})])
    patch_servers(monkeypatch, [server])

    result, events = await run(tmp_path=tmp_path)

    assert not result.success
    assert result.reason == "model exploded"
    assert events[-1][1]["to"] == "failed"
    assert events[-1][1]["error"] == {"code": "codex_error", "message": "model exploded"}


@pytest.mark.asyncio
async def test_cancellation_returns_cancelled(monkeypatch, tmp_path):
    server = FakeAppServer([])
    patch_servers(monkeypatch, [server])
    cancel = asyncio.Event()
    cancel.set()

    result, events = await run(tmp_path=tmp_path, cancel=cancel)

    assert result.reason == "cancelled"
    assert events[-1][1]["to"] == "cancelled"
    assert server.terminated


@pytest.mark.asyncio
async def test_timeout_returns_timeout(monkeypatch, tmp_path):
    server = FakeAppServer([])
    patch_servers(monkeypatch, [server])
    limits = ResolvedLimits(max_iterations=10, max_tokens=10**9, timeout_seconds=0)

    result, events = await run(tmp_path=tmp_path, limits=limits)

    assert result.reason == "timeout"
    assert events[-1][1]["to"] == "timed_out"
    assert server.terminated


@pytest.mark.asyncio
async def test_missing_binary_reports_unavailable(monkeypatch, tmp_path):
    async def boom(cmd, *, cwd, env):
        raise FileNotFoundError("codex")

    monkeypatch.setattr("agentcore.drivers.codex.start_app_server", boom)

    result, events = await run(tmp_path=tmp_path)

    assert result.reason == "codex_unavailable"
    assert events[-1][1]["error"]["code"] == "codex_unavailable"


@pytest.mark.asyncio
async def test_failed_thread_start_fails_cleanly(monkeypatch, tmp_path):
    server = FakeAppServer(fail={"thread/start": "no auth"})
    patch_servers(monkeypatch, [server])

    result, events = await run(tmp_path=tmp_path)

    assert result.reason == "codex_error"
    assert events[-1][1]["error"]["code"] == "codex_error"
    assert "no auth" in events[-1][1]["error"]["message"]
    assert not server.alive


@pytest.mark.asyncio
async def test_process_exit_without_turn_completed(monkeypatch, tmp_path):
    patch_servers(monkeypatch, [FakeAppServer([note("_exit", returncode=2)])])

    result, events = await run(tmp_path=tmp_path)

    assert result.reason == "codex exited 2"
    assert events[-1][1]["error"]["code"] == "codex_nonzero_exit"


@pytest.mark.asyncio
async def test_stderr_lines_become_codex_stdout(monkeypatch, tmp_path):
    patch_servers(monkeypatch, [FakeAppServer([note("_stderr", line="warn: x"), *answer("ok")])])

    _, events = await run(tmp_path=tmp_path)

    assert ("codex_stdout", {"line": "warn: x"}) in events


@pytest.mark.asyncio
async def test_declined_client_request_is_logged(monkeypatch, tmp_path):
    patch_servers(monkeypatch, [FakeAppServer([note("_declined", request="item/x"),
                                               *answer("ok")])])

    _, events = await run(tmp_path=tmp_path)

    logs = [p for t, p in events if t == "log" and p.get("op") == "codex_client_request_declined"]
    assert logs and logs[0]["request"] == "item/x"


@pytest.mark.asyncio
async def test_oauth_subscription_writes_auth_json(monkeypatch, tmp_path):
    from pathlib import Path

    from agentcore.drivers.codex import codex_home

    patch_servers(monkeypatch, [FakeAppServer(answer("ok"))])

    await run(tmp_path=tmp_path, credential="access-tok", credential_kind="oauth_subscription",
              credential_meta={"refresh_token": "ref", "account_id": "acct"})

    data = json.loads((Path(codex_home(str(tmp_path))) / "auth.json").read_text())
    assert data["tokens"]["access_token"] == "access-tok"
    assert data["tokens"]["refresh_token"] == "ref"


def test_codex_self_registers():
    import agentcore.drivers.codex  # noqa: F401
    from agentcore.drivers.base import DRIVERS

    assert "codex" in DRIVERS


def test_codex_capabilities_and_template():
    import agentcore.drivers.codex  # noqa: F401
    from agentcore.drivers.base import DRIVERS

    d = DRIVERS["codex"]
    assert d.capabilities.supports_tools is False
    assert d.capabilities.supports_structured_output is True
    assert d.capabilities.supports_cancel is True
    assert d.capabilities.requires_image_feature is None
    assert d.default_template.driver == "codex"
    assert d.default_template.available_tools == [
        "web_search", "image_generation", "view_image", "multi_agent", "goals",
    ]
    assert d.default_template.tools_user_editable is True
    assert d.default_template.supports_context is False


@pytest.mark.asyncio
async def test_one_off_task_deletes_its_thread(monkeypatch, tmp_path):
    server = FakeAppServer(answer("hi"), thread_id="thr_x")
    patch_servers(monkeypatch, [server])

    await run(tmp_path=tmp_path)

    assert server.params("thread/start")[0]["ephemeral"] is False
    assert server.params("thread/delete") == [{"threadId": "thr_x"}]


@pytest.mark.asyncio
async def test_session_first_turn_keeps_its_thread_and_writes_state(monkeypatch, tmp_path):
    from agentcore.drivers.session_state import read_session_state

    server = FakeAppServer(answer("hi"), thread_id="codex-thread-1")
    patch_servers(monkeypatch, [server])

    result, _ = await run(tmp_path=tmp_path, session_id="sess-1",
                          session_is_continuation=False)

    assert result.success is True
    assert "thread/delete" not in server.methods()
    assert read_session_state(str(tmp_path), "codex", "sess-1") == {"thread_id": "codex-thread-1"}


@pytest.mark.asyncio
async def test_session_continuation_resumes_the_thread(monkeypatch, tmp_path):
    from agentcore.drivers.session_state import write_session_state

    write_session_state(str(tmp_path), "codex", "sess-2", {"thread_id": "codex-thread-1"})
    server = FakeAppServer(answer("ok"))
    patch_servers(monkeypatch, [server])

    result, _ = await run(TaskBody(prompt="continue"), tmp_path=tmp_path, session_id="sess-2",
                          session_is_continuation=True)

    assert result.success is True
    assert server.methods()[:2] == ["thread/resume", "turn/start"]
    assert server.params("thread/resume")[0]["threadId"] == "codex-thread-1"
    assert server.params("turn/start")[0]["threadId"] == "codex-thread-1"
    assert "thread/delete" not in server.methods()


@pytest.mark.asyncio
async def test_session_missing_state_fails_fast(tmp_path):
    result, _ = await run(TaskBody(prompt="hi"), tmp_path=tmp_path, session_id="sess-missing",
                          session_is_continuation=True)

    assert result.success is False
    assert result.reason == "session_state_lost"


@pytest.mark.asyncio
async def test_configured_tools_reach_the_command(monkeypatch, tmp_path):
    starts = patch_servers(monkeypatch, [FakeAppServer(answer("hi"))])
    config = AgentConfig(driver="codex", model="gpt-5-codex", tools=["goals"])

    await run(config=config, tmp_path=tmp_path)

    cmd = starts[0]["cmd"]
    assert cmd[:2] == ["codex", "app-server"]
    assert cmd[cmd.index("features.goals=true") - 1] == "-c"
    assert "web_search=disabled" in cmd


@pytest.mark.asyncio
async def test_resumed_run_passes_configured_tools(monkeypatch, tmp_path):
    from agentcore.drivers.session_state import write_session_state

    write_session_state(str(tmp_path), "codex", "sess-tools", {"thread_id": "thr_t"})
    starts = patch_servers(monkeypatch, [FakeAppServer(answer("ok"))])
    config = AgentConfig(driver="codex", model="gpt-5-codex", tools=["goals"])

    await run(config=config, tmp_path=tmp_path, session_id="sess-tools",
              session_is_continuation=True)

    assert "features.goals=true" in starts[0]["cmd"]


@pytest.mark.asyncio
async def test_system_prompt_travels_as_developer_instructions(monkeypatch, tmp_path):
    from pathlib import Path

    from agentcore.drivers.codex import codex_config_path

    server = FakeAppServer(answer("ok"))
    patch_servers(monkeypatch, [server])
    config = AgentConfig(driver="codex", model="gpt-5-codex",
                         system_prompt="You are a security auditor.", tools=[])

    await run(config=config, tmp_path=tmp_path)

    params = server.params("thread/start")[0]
    assert params["developerInstructions"] == "You are a security auditor."
    assert params["model"] == "gpt-5-codex"
    assert not Path(codex_config_path(str(tmp_path))).exists()


@pytest.mark.asyncio
async def test_run_removes_agents_md_written_by_older_driver(monkeypatch, tmp_path):
    import pathlib

    from agentcore.drivers.codex import codex_home

    stale = pathlib.Path(codex_home(str(tmp_path))) / "AGENTS.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old prompt")
    patch_servers(monkeypatch, [FakeAppServer(answer("ok"))])

    await run(tmp_path=tmp_path)

    assert not stale.exists()


@pytest.mark.asyncio
async def test_task_prompt_is_sent_verbatim(monkeypatch, tmp_path):
    server = FakeAppServer(answer("ok"))
    patch_servers(monkeypatch, [server])
    config = AgentConfig(driver="codex", model="gpt-5-codex", system_prompt="Answer tersely.",
                         tools=[])

    await run(TaskBody(prompt="what is DNS?"), config, tmp_path=tmp_path)

    assert server.params("turn/start")[0]["input"] == [{"type": "text", "text": "what is DNS?"}]


@pytest.mark.asyncio
async def test_effort_and_reasoning_summary_travel_with_the_turn(monkeypatch, tmp_path):
    server = FakeAppServer(answer("hi"))
    patch_servers(monkeypatch, [server])
    config = cfg().model_copy(update={"reasoning_summary": True, "effort": "high"})

    await run(config=config, tmp_path=tmp_path)

    params = server.params("turn/start")[0]
    assert params["summary"] == "auto"
    assert params["effort"] == "high"


# Structured output: native outputSchema + validate-and-retry loop

STRUCT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def structured_task():
    return TaskBody(prompt="answer me", output={"type": "structured", "schema": STRUCT_SCHEMA})


@pytest.mark.asyncio
async def test_structured_valid_first_attempt(monkeypatch, tmp_path):
    server = FakeAppServer(answer('{"answer": "42"}'))
    patch_servers(monkeypatch, [server])

    result, events = await run(structured_task(), tmp_path=tmp_path)

    assert result.success is True
    assert result.output == {"answer": "42"}
    completed = [p for t, p in events if t == "status_change" and p["to"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["result"] == {"success": True, "output": {"answer": "42"}}
    turn = server.params("turn/start")[0]
    assert "## Output" in turn["input"][0]["text"]
    assert turn["outputSchema"] == STRUCT_SCHEMA
    assert "thread/delete" not in server.methods()


@pytest.mark.asyncio
async def test_structured_retries_then_succeeds(monkeypatch, tmp_path):
    bad = FakeAppServer(answer("not json at all"), thread_id="th_1")
    good = FakeAppServer(answer('{"answer": "42"}'))
    starts = patch_servers(monkeypatch, [bad, good])

    result, events = await run(structured_task(), tmp_path=tmp_path)

    assert result.success is True
    assert result.output == {"answer": "42"}
    assert len(starts) == 2
    assert good.params("thread/resume")[0]["threadId"] == "th_1"
    assert "Invalid output" in good.params("turn/start")[0]["input"][0]["text"]
    warns = [p for t, p in events if t == "log" and p["message"] == "structured_output_invalid"]
    assert len(warns) == 1
    completed = [p for t, p in events if t == "status_change" and p["to"] == "completed"]
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_structured_fails_after_max_attempts(monkeypatch, tmp_path):
    from agentcore.structured_output import MAX_ATTEMPTS

    servers = [FakeAppServer(answer("still not json")) for _ in range(MAX_ATTEMPTS)]
    starts = patch_servers(monkeypatch, list(servers))

    result, events = await run(structured_task(), tmp_path=tmp_path)

    assert result.success is False
    assert result.reason == "invalid_structured_output"
    assert len(starts) == MAX_ATTEMPTS
    failed = [p for t, p in events if t == "status_change" and p["to"] == "failed"]
    assert failed[-1]["error"]["code"] == "invalid_structured_output"


@pytest.mark.asyncio
async def test_structured_no_native_schema_for_incompatible_schema(monkeypatch, tmp_path):
    task = TaskBody(prompt="p", output={"type": "structured",
                                        "schema": {"type": "array", "items": {"type": "string"}}})
    server = FakeAppServer(answer('["a"]'))
    patch_servers(monkeypatch, [server])

    result, _ = await run(task, tmp_path=tmp_path)

    assert "outputSchema" not in server.params("turn/start")[0]
    assert result.output == ["a"]


def test_codex_supports_structured_output():
    from agentcore.drivers.codex import CodexDriver

    assert CodexDriver.capabilities.supports_structured_output is True


# Progress updates: envelope messages become `progress` events


def progress_cfg():
    return cfg().model_copy(update={"progress_updates": True})


def envelope(progress=None, result=None):
    return json.dumps({"progress": progress, "result": result})


@pytest.mark.asyncio
async def test_progress_messages_become_progress_events_for_a_text_task(monkeypatch, tmp_path):
    server = FakeAppServer(answer(envelope(progress="Vou ler o ficheiro."),
                                  envelope(result="Feito.")))
    patch_servers(monkeypatch, [server])

    result, events = await run(TaskBody(prompt="olá"), progress_cfg(), tmp_path=tmp_path)

    assert [p for t, p in events if t == "progress"] == [{"text": "Vou ler o ficheiro."}]
    assert result.output == "Feito."
    completed = [p for t, p in events if t == "status_change" and p["to"] == "completed"]
    assert completed[0]["result"] == {"success": True, "output": "Feito."}
    schema = server.params("turn/start")[0]["outputSchema"]
    assert schema["properties"]["result"] == {"type": ["string", "null"]}


@pytest.mark.asyncio
async def test_progress_messages_for_a_structured_task_return_the_unwrapped_answer(
    monkeypatch, tmp_path
):
    server = FakeAppServer(answer(envelope(progress="A calcular."),
                                  envelope(result={"answer": "42"})))
    patch_servers(monkeypatch, [server])

    result, events = await run(structured_task(), progress_cfg(), tmp_path=tmp_path)

    assert [p for t, p in events if t == "progress"] == [{"text": "A calcular."}]
    assert result.output == {"answer": "42"}
    schema = server.params("turn/start")[0]["outputSchema"]
    assert schema["properties"]["result"]["anyOf"][0] == STRUCT_SCHEMA


@pytest.mark.asyncio
async def test_progress_updates_accept_a_bare_answer_without_the_envelope(monkeypatch, tmp_path):
    non_native = {"type": "array", "items": {"type": "string", "minLength": 1}}
    task = TaskBody(prompt="p", output={"type": "structured", "schema": non_native})
    server = FakeAppServer(answer('["a"]'))
    patch_servers(monkeypatch, [server])

    result, _ = await run(task, progress_cfg(), tmp_path=tmp_path)

    assert "outputSchema" not in server.params("turn/start")[0]
    assert result.output == ["a"]


@pytest.mark.asyncio
async def test_progress_rules_travel_in_developer_instructions(monkeypatch, tmp_path):
    from agentcore.drivers.codex import PROGRESS_INSTRUCTIONS

    server = FakeAppServer(answer(envelope(result="ok")))
    patch_servers(monkeypatch, [server])

    await run(TaskBody(prompt="hi"), progress_cfg(), tmp_path=tmp_path)

    instructions = server.params("thread/start")[0]["developerInstructions"]
    assert PROGRESS_INSTRUCTIONS.splitlines()[0] in instructions


@pytest.mark.asyncio
async def test_envelope_text_is_left_alone_when_progress_updates_are_off(monkeypatch, tmp_path):
    text = envelope(progress="x")
    server = FakeAppServer(answer(text))
    patch_servers(monkeypatch, [server])

    result, events = await run(TaskBody(prompt="hi"), tmp_path=tmp_path)

    assert not [p for t, p in events if t == "progress"]
    assert result.output == text
    assert "outputSchema" not in server.params("turn/start")[0]

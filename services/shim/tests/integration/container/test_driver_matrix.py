# services/shim/tests/integration/container/test_driver_matrix.py
#
# All drivers (vanilla + CLI) now map done(success=False) → task status "failed".
# This is the uniform contract: model-reported failure is a task failure.
#
# `api` is the odd one out: no tools, no `done` contract, single direct LLM
# call per task. It shares the plain success path (any scripted turn that
# completes the one call) but is exempted from the `done`-tool-shaped
# scenarios below and gets its own prompt-only coverage instead.
#
import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration

ALL_DRIVERS = ["vanilla", "opencode", "codex", "claude-code", "api"]


@pytest.mark.parametrize("driver", ALL_DRIVERS)
def test_success_completes(client, driver):
    tid = f"tsk_ok_{driver}".replace("-", "_")
    turns = [{"done": {"success": True, "output": "all good"}}]
    body = sc.task_body(tid, driver, turns=turns,
                        usage={"input_tokens": 10, "output_tokens": 5})
    assert client.post("/tasks", json=body).status_code == 200
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "completed", status
    assert status["tokens_in"] == 10 and status["tokens_out"] == 5


@pytest.mark.parametrize("driver", ALL_DRIVERS)
def test_model_error_fails(client, driver):
    """All drivers propagate model-refusal as task status 'failed'.

    `api` has no `done` tool, so it never observes this signal — it is
    exempted here and gets its own failure-mode test
    (test_api_structured_output_retry_exhaustion_fails) below.
    """
    if driver == "api":
        pytest.skip("api driver has no `done` tool / tool-use contract")
    tid = f"tsk_err_{driver}".replace("-", "_")
    turns = [{"done": {"success": False, "reason": "cannot comply"}}]
    body = sc.task_body(tid, driver, turns=turns)
    client.post("/tasks", json=body)
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "failed", status


@pytest.mark.parametrize("driver", ALL_DRIVERS)
def test_writes_workspace_file(client, driver):
    """All drivers can write workspace files via a tool call.

    `api` supports no tools and makes no workspace writes — exempted here
    and covered by test_api_ignores_tool_scenario below.
    """
    if driver == "api":
        pytest.skip("api driver supports no tools and makes no workspace writes")
    tid = f"tsk_file_{driver}".replace("-", "_")
    turns = [{"tool": "write_file",
              "input": {"path": f"{tid}.md", "content": "hello-file"}},
             {"done": {"success": True, "output": "wrote"}}]
    body = sc.task_body(tid, driver, turns=turns)
    client.post("/tasks", json=body)
    sc.poll_terminal(client, tid)
    raw = client.get("/files/raw", params={"path": f"{tid}.md"})
    assert raw.status_code == 200
    assert raw.text == "hello-file"


def test_api_prompt_only_completes(client):
    """api driver: a single direct LLM call, no tools, no `done` contract —
    a bare text turn is enough for the task to complete."""
    tid = "tsk_api_prompt_only"
    turns = [{"text": "The answer is 42."}]
    body = sc.task_body(tid, "api", turns=turns, tools=[],
                        usage={"input_tokens": 8, "output_tokens": 4})
    assert client.post("/tasks", json=body).status_code == 200
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "completed", status
    assert status["result"] == {"success": True, "output": "The answer is 42."}
    assert status["tokens_in"] == 8 and status["tokens_out"] == 4


def test_api_ignores_tool_scenario(client):
    """api driver spurns tool-use scenarios: it has no tools configured and
    completes after its single call regardless of any scripted tool_use
    content — no workspace write ever happens."""
    tid = "tsk_api_ignores_tools"
    turns = [{"tool": "write_file",
              "input": {"path": f"{tid}.md", "content": "should-not-write"}}]
    body = sc.task_body(tid, "api", turns=turns, tools=[])
    assert client.post("/tasks", json=body).status_code == 200
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "completed", status
    raw = client.get("/files/raw", params={"path": f"{tid}.md"})
    assert raw.status_code == 404


def test_api_structured_output_retry_exhaustion_fails(client):
    """api driver's own failure mode: structured output that never parses
    exhausts its bounded retry loop (no `done` tool involved) — the
    api-native analog of test_model_error_fails above."""
    tid = "tsk_api_bad_structured"
    turns = [{"text": "not json"}, {"text": "still not json"}, {"text": "nope"}]
    schema = {"type": "object", "required": ["x"],
              "properties": {"x": {"type": "string"}}}
    body = sc.task_body(tid, "api", turns=turns, tools=[],
                        output={"type": "structured", "schema": schema})
    assert client.post("/tasks", json=body).status_code == 200
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "failed", status


def test_meta_all_registered_drivers_in_matrix():
    import agentcore.drivers  # noqa: F401  (registers all drivers into DRIVERS)
    from agentcore.drivers.base import DRIVERS
    assert set(DRIVERS.keys()) == set(ALL_DRIVERS), (
        "every registered driver must appear in the container matrix"
    )

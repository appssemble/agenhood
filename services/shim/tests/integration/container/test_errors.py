# services/shim/tests/integration/container/test_errors.py
#
# Error-path scenarios:
#   - malformed request body → synchronous FastAPI 422
#   - unknown driver → POST 200 (accepted), then async-failed with
#     error.code == "validation_error"  (see runner.py:_fail_unknown_driver)
#   - missing task GET/cancel → 404
#   - overloaded LLM (http_error 529 via @@SCRIPT@@) → task failed
#   - stub sleeps past timeout_seconds → timed_out
#   - CLI drivers with never_done=True past tight timeout → timed_out or failed
#
# delay_ms margins:
#   timeout test: delay_ms=8000 >> timeout_seconds=2 (4× margin)
#   cli hang   :  timeout_seconds=2 with never_done; deadline polls 30 s
import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration


def test_malformed_payload_422(client):
    # The handler wraps ShimTaskRequest.model_validate(body) in a try/except so
    # pydantic.ValidationError is caught and re-raised as HTTPException 422.
    resp = client.post("/tasks", json={"task_id": "x"})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_non_json_body_422(client):
    # The other caught branch: a body that is not valid JSON raises
    # json.JSONDecodeError, which the handler also maps to 422 (not 500).
    resp = client.post(
        "/tasks", content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_unknown_driver_async_fails(client):
    # POST is accepted synchronously (200); driver resolution happens in the
    # background task and emits a terminal "failed" + validation_error.
    body = sc.task_body(
        "tsk_unknown_drv", "no-such-driver",
        turns=[{"done": {"success": True, "output": "ok"}}],
    )
    assert client.post("/tasks", json=body).status_code == 200
    status = sc.poll_terminal(client, "tsk_unknown_drv")
    assert status["status"] == "failed", status
    assert status["error"]["code"] == "validation_error", status


def test_missing_task_404(client):
    assert client.get("/tasks/ghost").status_code == 404
    assert client.post("/tasks/ghost/cancel").status_code == 404


def test_overloaded_llm_fails_vanilla(client):
    # @@SCRIPT@@ http_error flag: the stub responds with the given HTTP status,
    # simulating an overloaded upstream (529).  The vanilla driver surfaces this
    # as a task failure.
    body = sc.task_body(
        "tsk_overloaded", "vanilla",
        turns=[],
        http_error={"status": 529},
    )
    client.post("/tasks", json=body)
    status = sc.poll_terminal(client, "tsk_overloaded")
    assert status["status"] == "failed", status


def test_timeout_fires_for_long_running_vanilla_task(client):
    # The vanilla driver checks timeout at the TOP of each iteration (not mid-LLM-call),
    # so delay_ms alone cannot trigger a timeout when the task has only one done turn
    # (the LLM call returns after delay_ms and the task completes immediately).
    # Fix: use never_done=True so the stub never calls done(); the driver loops
    # indefinitely and the timeout check fires after timeout_seconds.
    # max_iterations is set high (1000) so the iteration limit never fires first.
    body = sc.task_body(
        "tsk_timeout", "vanilla",
        turns=[],
        never_done=True,
        limits={"max_iterations": 1000, "max_tokens": 1_000_000,
                "timeout_seconds": 2},
    )
    client.post("/tasks", json=body)
    status = sc.poll_terminal(client, "tsk_timeout", timeout=30)
    assert status["status"] == "timed_out", status


@pytest.mark.parametrize("driver", ["opencode", "codex", "claude-code"])
def test_cli_never_done_times_out(client, driver):
    # CLI stubs with never_done=True never emit a done() call; the task must
    # reach timed_out (or failed) before the 30 s poll deadline.
    tid = f"tsk_hang_{driver}".replace("-", "_")
    body = sc.task_body(
        tid, driver,
        turns=[],
        never_done=True,
        limits={"max_iterations": 8, "max_tokens": 1_000_000,
                "timeout_seconds": 2},
    )
    client.post("/tasks", json=body)
    status = sc.poll_terminal(client, tid, timeout=30)
    assert status["status"] in ("timed_out", "failed"), status

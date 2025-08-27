# services/shim/tests/integration/container/test_driver_matrix.py
#
# All drivers (vanilla + CLI) now map done(success=False) → task status "failed".
# This is the uniform contract: model-reported failure is a task failure.
#
import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration

ALL_DRIVERS = ["vanilla", "opencode", "codex", "claude-code"]


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
    """All drivers propagate model-refusal as task status 'failed'."""
    tid = f"tsk_err_{driver}".replace("-", "_")
    turns = [{"done": {"success": False, "reason": "cannot comply"}}]
    body = sc.task_body(tid, driver, turns=turns)
    client.post("/tasks", json=body)
    status = sc.poll_terminal(client, tid)
    assert status["status"] == "failed", status


@pytest.mark.parametrize("driver", ALL_DRIVERS)
def test_writes_workspace_file(client, driver):
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


def test_meta_all_registered_drivers_in_matrix():
    import agentcore.drivers  # noqa: F401  (registers all drivers into DRIVERS)
    from agentcore.drivers.base import DRIVERS
    assert set(DRIVERS.keys()) == set(ALL_DRIVERS), (
        "every registered driver must appear in the container matrix"
    )

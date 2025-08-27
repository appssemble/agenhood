# services/shim/tests/integration/container/test_concurrency.py
#
# Concurrency contract tests against the LIVE shim stack (SHIM_MAX_WORKERS=4).
#
# Shutdown ordering note: /shutdown cancels running tasks but does NOT kill the
# server — the FastAPI app stays up, /healthz keeps answering, and new tasks
# are accepted after the call. Therefore test_shutdown_cancels_running_but_server_stays_up
# can safely sit 4th (not last) without poisoning the module-scoped stack.
#
# delay_ms margins:
#   fill tasks (429 test)  : 4 000 ms — tasks post near-instantly so all 4 are
#                            "running" before the 5th POST lands; completes in ≤5 s.
#   cancel test long side  : 6 000 ms — long enough to cancel reliably before done.
#   shutdown test           : 8 000 ms — ensures the task is still running when
#                            /shutdown is called.
import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration


def _slow_body(tid, driver="vanilla", delay_ms=4000):
    # delay keeps the task 'running' so concurrency limits are observable.
    return sc.task_body(tid, driver,
                        turns=[{"done": {"success": True, "output": "ok"}}],
                        delay_ms=delay_ms,
                        limits={"max_iterations": 8, "max_tokens": 1_000_000,
                                "timeout_seconds": 30})


def test_max_workers_rejects_overflow_with_429(client):
    # Fill the 4 worker slots with slow tasks, then the 5th must 429.
    for i in range(4):
        assert client.post("/tasks", json=_slow_body(f"tsk_cc_fill_{i}")
                           ).status_code == 200
    overflow = client.post("/tasks", json=_slow_body("tsk_cc_overflow"))
    assert overflow.status_code == 429
    assert overflow.json()["error"]["code"] == "too_many_tasks"
    # Drain so active slots are free for subsequent tests.
    for i in range(4):
        sc.poll_terminal(client, f"tsk_cc_fill_{i}", timeout=30)


def test_tasks_are_isolated(client):
    a = sc.task_body("tsk_iso_a", "vanilla",
                     turns=[{"done": {"success": True, "output": "AAA"}}])
    b = sc.task_body("tsk_iso_b", "vanilla",
                     turns=[{"done": {"success": False, "reason": "BBB"}}])
    client.post("/tasks", json=a)
    client.post("/tasks", json=b)
    sa = sc.poll_terminal(client, "tsk_iso_a")
    sb = sc.poll_terminal(client, "tsk_iso_b")
    assert sa["status"] == "completed" and sa["result"]["output"] == "AAA"
    assert sb["status"] == "failed"


def test_cancel_one_leaves_sibling(client):
    long_a = _slow_body("tsk_cancel_a", delay_ms=6000)
    short_b = sc.task_body("tsk_keep_b", "vanilla",
                           turns=[{"done": {"success": True, "output": "ok"}}])
    client.post("/tasks", json=long_a)
    client.post("/tasks", json=short_b)
    client.post("/tasks/tsk_cancel_a/cancel")
    sa = sc.poll_terminal(client, "tsk_cancel_a")
    sb = sc.poll_terminal(client, "tsk_keep_b")
    assert sa["status"] in ("cancelled", "completed")
    assert sb["status"] == "completed"


def test_shutdown_cancels_running_but_server_stays_up(client):
    # /shutdown returns {"shutting_down": True} and leaves /healthz answering.
    # The server continues accepting requests after this call — no fixture teardown.
    client.post("/tasks", json=_slow_body("tsk_shutdown_x", delay_ms=8000))
    assert client.post("/shutdown").json() == {"shutting_down": True}
    sc.poll_terminal(client, "tsk_shutdown_x", timeout=30)
    assert client.get("/healthz").json() == {"ok": True}


def test_duplicate_task_id_overwrites(client):
    first = sc.task_body("tsk_dup", "vanilla",
                         turns=[{"done": {"success": True, "output": "first"}}])
    client.post("/tasks", json=first)
    sc.poll_terminal(client, "tsk_dup")
    second = sc.task_body("tsk_dup", "vanilla",
                          turns=[{"done": {"success": True, "output": "second"}}])
    assert client.post("/tasks", json=second).status_code == 200
    status = sc.poll_terminal(client, "tsk_dup")
    assert status["result"]["output"] == "second"

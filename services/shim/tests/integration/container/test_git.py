# services/shim/tests/integration/container/test_git.py
#
# Git-snapshot scenarios:
#   - auto-commit after a task with git_snapshots=True appears in /git/log
#   - /git/status responds
#   - rollback to an unknown SHA returns 404
#
# Shape notes (verified against shim/app.py + shim/git_ops.py):
#   GET /git/log  → {"snapshots": [{"sha","ts","message","task_id","files_changed"},...]}
#   POST /git/rollback {"sha": "<unknown>"} → 404 (unknown_sha GitError)
import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration


def _git_task(tid: str, content: str) -> dict:
    body = sc.task_body(
        tid, "vanilla",
        turns=[
            {"tool": "write_file",
             "input": {"path": f"{tid}.md", "content": content}},
            {"done": {"success": True, "output": "ok"}},
        ],
    )
    body["git_snapshots"] = True
    return body


def test_task_auto_commit_appears_in_log(client):
    tid = "tsk_git_commit"
    client.post("/tasks", json=_git_task(tid, "v1"))
    sc.poll_terminal(client, tid)
    log = client.get("/git/log").json()
    # /git/log returns {"snapshots": [...]} — each entry has a "message" field
    # shaped as "task <task_id>: <status>"
    msgs = [c.get("message", "") for c in log.get("snapshots", [])]
    assert any(tid in m for m in msgs), log


def test_status_endpoint_responds(client):
    r = client.get("/git/status")
    assert r.status_code == 200
    body = r.json()
    # Must have an "initialized" field (workspace git rollback spec)
    assert "initialized" in body


def test_rollback_unknown_sha_returns_404(client):
    # Providing a valid-looking but non-existent SHA triggers GitError("unknown_sha")
    # which app.py maps to HTTP 404.
    r = client.post(
        "/git/rollback",
        json={"sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
    )
    assert r.status_code == 404

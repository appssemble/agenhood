# services/shim/tests/test_app_git.py
from __future__ import annotations

import asyncio
import subprocess

import httpx
import pytest

from agentcore.drivers.base import DriverCapabilities, DriverTemplate
from agentcore.models import TaskResult
from shim.app import create_app

pytestmark = pytest.mark.unit


class SlowDriver:
    """Stays running until cancelled — for the rollback-while-running test."""
    name = "vanilla"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("vanilla", "p", [], True, True)

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", **_kwargs: object):
        await cancel.wait()
        return TaskResult(success=False, reason="cancelled")


def app_client(tmp_path, driver=None):
    app = create_app(
        workspace=str(tmp_path), token="",
        drivers={"vanilla": driver or SlowDriver()},
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://shim")


def task_payload(task_id="tsk_1"):
    return {
        "task_id": task_id,
        "task": {"prompt": "hi", "output": {"type": "text"}},
        "config": {"driver": "vanilla", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk-secret",
    }


@pytest.mark.asyncio
async def test_git_status_initializes_lazily(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.get("/git/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["initialized"] is True
        assert len(body["head"]) == 40


@pytest.mark.asyncio
async def test_git_log_returns_snapshots(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.get("/git/log")
        assert resp.status_code == 200
        snaps = resp.json()["snapshots"]
        assert len(snaps) == 1
        assert snaps[0]["message"] == "initial snapshot"


@pytest.mark.asyncio
async def test_rollback_unknown_sha_404(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.post("/git/rollback", json={"sha": "0" * 40})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rollback_refused_while_task_running(tmp_path):
    async with app_client(tmp_path) as c:
        await c.post("/tasks", json=task_payload())
        head = (await c.get("/git/status")).json()["head"]
        resp = await c.post("/git/rollback", json={"sha": head})
        assert resp.status_code == 409
        await c.post("/tasks/tsk_1/cancel")


@pytest.mark.asyncio
async def test_rollback_happy_path(tmp_path):
    async with app_client(tmp_path) as c:
        head = (await c.get("/git/status")).json()["head"]
        (tmp_path / "f.txt").write_text("x")
        resp = await c.post("/git/rollback", json={"sha": head})
        assert resp.status_code == 200
        assert resp.json()["sha"] != head
        assert not (tmp_path / "f.txt").exists()


@pytest.mark.asyncio
async def test_verify_route_returns_branches(tmp_path, monkeypatch):
    from shim import git_ops

    async def fake_verify(self, *, url, ssh_private_key):
        return {"branches": ["main", "dev"], "default_branch": "main"}

    monkeypatch.setattr(git_ops.GitOps, "verify_remote", fake_verify)
    async with app_client(tmp_path) as c:
        r = await c.post(
            "/git/verify",
            json={"url": "git@github.com:a/b.git", "ssh_private_key": "K"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["branches"] == ["main", "dev"]
        assert body["default_branch"] == "main"


@pytest.mark.asyncio
async def test_git_push_and_verify_roundtrip(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    async with app_client(ws) as c:
        ok = await c.post("/git/verify", json={"url": str(bare), "ssh_private_key": ""})
        assert ok.json()["ok"] is True
        assert "branches" in ok.json()
        assert "default_branch" in ok.json()
        bad = await c.post(
            "/git/verify",
            json={"url": str(tmp_path / "nope.git"), "ssh_private_key": ""},
        )
        assert bad.json()["ok"] is False
        pushed = await c.post(
            "/git/push",
            json={"url": str(bare), "ssh_private_key": "", "branch": "main"},
        )
        assert pushed.json()["ok"] is True
        assert len(pushed.json()["sha"]) == 40


class OkDriver:
    name = "vanilla"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("vanilla", "p", [], True, True)

    def __init__(self, workspace_file: str | None = None):
        self._file = workspace_file

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", **_kwargs: object):
        if self._file:
            import pathlib
            pathlib.Path(workspace, self._file).write_text("made by task")
        await emit("status_change", {"from": "running", "to": "completed",
                                     "result": "done", "error": None})
        return TaskResult(success=True, output="done")


async def _wait_terminal(c, task_id):
    for _ in range(100):
        got = (await c.get(f"/tasks/{task_id}")).json()
        if got["status"] != "running":
            return got
        await asyncio.sleep(0.02)
    raise AssertionError("task never finished")


@pytest.mark.asyncio
async def test_auto_commit_after_task(tmp_path):
    async with app_client(tmp_path, driver=OkDriver("out.txt")) as c:
        await c.post("/tasks", json=task_payload())
        await _wait_terminal(c, "tsk_1")
        await asyncio.sleep(0.1)                      # let the post-task hook run
        snaps = (await c.get("/git/log")).json()["snapshots"]
        assert snaps[0]["message"] == "task tsk_1: completed"
        assert snaps[0]["task_id"] == "tsk_1"


async def _wait_for_event(c, task_id, event_type, timeout=5.0):
    """Poll the events replay until an event of `event_type` is in the log.

    The post-task git hook runs AFTER the task goes terminal and spawns
    several git subprocesses, while the events route closes its replay
    immediately once status is terminal — so a fixed sleep races against
    the hook and is flaky under load. Poll with a deadline instead.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        text = (await c.get(f"/tasks/{task_id}/events")).text
        if f'"type": "{event_type}"' in text:
            return text
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"no {event_type!r} event within {timeout}s; events: {text!r}")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_auto_commit_emits_git_event(tmp_path):
    async with app_client(tmp_path, driver=OkDriver("out.txt")) as c:
        await c.post("/tasks", json=task_payload())
        await _wait_terminal(c, "tsk_1")
        text = await _wait_for_event(c, "tsk_1", "git")
        assert '"type": "git"' in text


@pytest.mark.asyncio
async def test_auto_push_when_git_push_block_present(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    async with app_client(ws, driver=OkDriver("out.txt")) as c:
        body = task_payload()
        body["git_push"] = {"url": str(bare), "ssh_private_key": "", "branch": "main"}
        await c.post("/tasks", json=body)
        await _wait_terminal(c, "tsk_1")
        # Wait explicitly for the push git-event: the post-task hook runs async
        # after the task goes terminal, and git is measurably slower when
        # HOME=/home/agent (build_child_env) does not exist on the test host.
        # asyncio.sleep(0.2) was a race-prone timing hack; poll instead.
        await _wait_for_event(c, "tsk_1", "git", timeout=15.0)
        # The first "git" event may be the commit; wait for the push payload too.
        deadline = asyncio.get_running_loop().time() + 15.0
        while '"op": "push"' not in (await c.get("/tasks/tsk_1/events")).text:
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("push git-event not emitted within 15 s")
            await asyncio.sleep(0.05)
        ws_head = (await c.get("/git/status")).json()["head"]
        remote_head = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "main"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert remote_head == ws_head


@pytest.mark.asyncio
async def test_git_failure_does_not_change_task_status(tmp_path, monkeypatch):
    from shim import git_ops

    async def boom(self, message):
        raise git_ops.GitError("git_commit_failed", "disk on fire")

    monkeypatch.setattr(git_ops.GitOps, "commit_all", boom)
    async with app_client(tmp_path, driver=OkDriver()) as c:
        await c.post("/tasks", json=task_payload())
        got = await _wait_terminal(c, "tsk_1")
        await asyncio.sleep(0.1)
        assert got["status"] == "completed"           # task outcome untouched


@pytest.mark.asyncio
async def test_post_task_git_skipped_when_snapshots_disabled(tmp_path, monkeypatch):
    """With git_snapshots=False the shim never auto-commits or touches the
    baseline repo (linked / pull mode: the agent owns git)."""
    from shim import git_ops

    calls = {"commit": 0, "ensure": 0}

    async def no_commit(self, message):
        calls["commit"] += 1
        return "0" * 40

    async def no_ensure(self):
        calls["ensure"] += 1
        return {"created": False, "reinitialized": False}

    monkeypatch.setattr(git_ops.GitOps, "commit_all", no_commit)
    monkeypatch.setattr(git_ops.GitOps, "ensure_repo", no_ensure)

    async with app_client(tmp_path, driver=OkDriver("out.txt")) as c:
        body = task_payload()
        body["git_snapshots"] = False
        await c.post("/tasks", json=body)
        got = await _wait_terminal(c, "tsk_1")
        await asyncio.sleep(0.1)                       # let the post-task hook run
        assert got["status"] == "completed"            # task ran normally
    # Neither the baseline snapshot nor the post-task commit happened.
    assert calls["ensure"] == 0
    assert calls["commit"] == 0


@pytest.mark.asyncio
async def test_git_clone_route_returns_sha(tmp_path, monkeypatch):
    from shim import git_ops

    async def fake_clone(self, *, url, ssh_private_key, branch):
        assert (url, branch) == ("git@h:o/r.git", "main")
        return "a" * 40

    monkeypatch.setattr(git_ops.GitOps, "clone", fake_clone)
    async with app_client(tmp_path) as c:
        r = await c.post("/git/clone", json={
            "url": "git@h:o/r.git", "ssh_private_key": "k", "branch": "main",
        })
        assert r.status_code == 200
        assert r.json() == {"sha": "a" * 40}


@pytest.mark.asyncio
async def test_git_clone_route_maps_git_error(tmp_path, monkeypatch):
    from shim import git_ops

    async def boom(self, *, url, ssh_private_key, branch):
        raise git_ops.GitError("auth_failed", "denied")

    monkeypatch.setattr(git_ops.GitOps, "clone", boom)
    async with app_client(tmp_path) as c:
        r = await c.post("/git/clone", json={
            "url": "git@h:o/r.git", "ssh_private_key": "k", "branch": "main",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "auth_failed"


@pytest.mark.asyncio
async def test_files_listing_excludes_git_internals(tmp_path):
    async with app_client(tmp_path) as c:
        await c.get("/git/status")                    # lazily init the repo
        (tmp_path / "visible.txt").write_text("x")
        files = (await c.get("/files")).json()["files"]
        paths = [f["path"] for f in files]
        assert "visible.txt" in paths
        assert not any(p.split("/")[0] == ".git" for p in paths)

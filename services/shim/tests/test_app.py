import asyncio
import json

import httpx
import pytest

from agentcore.drivers.base import DriverCapabilities, DriverTemplate
from agentcore.models import TaskResult
from shim.app import create_app

pytestmark = pytest.mark.unit


class FakeDriver:
    name = "vanilla"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("vanilla", "p", [], True, True)

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", **_kwargs: object):
        await emit("task_started", {"driver": "vanilla", "model": config.model})
        await emit("iteration_started", {"iteration": 1})
        await emit("status_change", {"from": "running", "to": "completed",
                                     "result": {"answer": 42}, "error": None})
        return TaskResult(success=True, output={"answer": 42})


def app_client(tmp_path):
    app = create_app(
        workspace=str(tmp_path), token="", drivers={"vanilla": FakeDriver()}
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://shim")


def task_payload():
    return {
        "task_id": "tsk_1",
        "task": {"prompt": "hi", "output": {"type": "text"}},
        "config": {"driver": "vanilla", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk-secret",
    }


@pytest.mark.asyncio
async def test_healthz_and_readyz(tmp_path):
    async with app_client(tmp_path) as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/readyz")).status_code == 200


@pytest.mark.asyncio
async def test_post_task_returns_running_then_completes(tmp_path):
    async with app_client(tmp_path) as c:
        resp = await c.post("/tasks", json=task_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "tsk_1"
        assert body["status"] == "running"
        # Let the background task finish.
        for _ in range(50):
            got = (await c.get("/tasks/tsk_1")).json()
            if got["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        assert got["status"] == "completed"
        assert got["result"] == {"answer": 42}


@pytest.mark.asyncio
async def test_get_unknown_task_404(tmp_path):
    async with app_client(tmp_path) as c:
        assert (await c.get("/tasks/nope")).status_code == 404


@pytest.mark.asyncio
async def test_events_replay_after_completion(tmp_path):
    async with app_client(tmp_path) as c:
        await c.post("/tasks", json=task_payload())
        for _ in range(50):
            if (await c.get("/tasks/tsk_1")).json()["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        resp = await c.get("/tasks/tsk_1/events")
        assert resp.status_code == 200
        seqs, types = [], []
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                obj = json.loads(line[len("data: "):])
                seqs.append(obj["seq"])
                types.append(obj["type"])
        assert seqs == [1, 2, 3]
        assert types[0] == "task_started"
        assert types[-1] == "status_change"


@pytest.mark.asyncio
async def test_events_after_seq_slices_strictly(tmp_path):
    async with app_client(tmp_path) as c:
        await c.post("/tasks", json=task_payload())
        for _ in range(50):
            if (await c.get("/tasks/tsk_1")).json()["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        resp = await c.get("/tasks/tsk_1/events?after_seq=2")
        seqs = [
            json.loads(line[len("data: "):])["seq"]
            for line in resp.text.splitlines() if line.startswith("data: ")
        ]
        assert seqs == [3]


@pytest.mark.asyncio
async def test_list_tasks(tmp_path):
    async with app_client(tmp_path) as c:
        await c.post("/tasks", json=task_payload())
        listing = (await c.get("/tasks")).json()
        assert any(t["task_id"] == "tsk_1" for t in listing["tasks"])


@pytest.mark.asyncio
async def test_auth_required_when_token_set(tmp_path):
    app = create_app(
        workspace=str(tmp_path), token="secret", drivers={"vanilla": FakeDriver()}
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://shim") as c:
        assert (await c.post("/tasks", json=task_payload())).status_code == 401
        ok = await c.post(
            "/tasks", json=task_payload(),
            headers={"Authorization": "Bearer secret"},
        )
        assert ok.status_code == 200


# ---- path-escape boundary regression -----------------------------------

def _sibling_evil_dir(tmp_path):
    """Create a sibling dir `<workspace>-evil` holding a secret, and return the
    `../`-relative path that resolves into it. A plain `startswith(ws)` prefix
    check wrongly treats `/workspace-evil` as inside `/workspace`."""
    evil = tmp_path.parent / (tmp_path.name + "-evil")
    evil.mkdir()
    (evil / "secret.txt").write_text("stolen")
    return f"../{tmp_path.name}-evil/secret.txt"


@pytest.mark.asyncio
async def test_download_rejects_sibling_path_escape(tmp_path):
    escape = _sibling_evil_dir(tmp_path)
    async with app_client(tmp_path) as c:
        resp = await c.get("/files/raw", params={"path": escape})
        assert resp.status_code == 400
        assert "escape" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_rejects_sibling_path_escape(tmp_path):
    escape = _sibling_evil_dir(tmp_path)
    async with app_client(tmp_path) as c:
        resp = await c.request("DELETE", "/files/raw", params={"path": escape})
        assert resp.status_code == 400
        assert "escape" in resp.json()["detail"]
    # The sibling file must remain untouched by the rejected delete.
    assert (tmp_path.parent / (tmp_path.name + "-evil") / "secret.txt").exists()


@pytest.mark.asyncio
async def test_upload_rejects_sibling_path_escape(tmp_path):
    escape = _sibling_evil_dir(tmp_path)
    async with app_client(tmp_path) as c:
        resp = await c.put("/files/raw", params={"path": escape}, content=b"pwned")
        assert resp.status_code == 400
    # The sibling file must be unchanged (not overwritten).
    assert (
        tmp_path.parent / (tmp_path.name + "-evil") / "secret.txt"
    ).read_text() == "stolen"

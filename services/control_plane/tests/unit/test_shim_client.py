import httpx
import pytest
import respx

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from control_plane.shim_client import ShimClient
from control_plane.snapshot import build_shim_request

pytestmark = pytest.mark.unit


def _client() -> ShimClient:
    return ShimClient(base_url="http://agent-c-abc:8080", token="sekret")


@respx.mock
async def test_submit_task_posts_to_tasks_with_auth_and_body():
    route = respx.post("http://agent-c-abc:8080/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "tsk_1",
                "status": "running",
                "started_at": "2026-05-20T00:00:00Z",
            },
        )
    )
    req = build_shim_request(
        task_id="tsk_1",
        body=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="claude-opus-4-7"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100, timeout_seconds=30),
        credential="sk-x",
    )
    async with _client() as c:
        resp = await c.submit_task(req)
    assert resp["status"] == "running"
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sekret"
    body = sent.read().decode()
    assert '"llm_credential":"sk-x"' in body.replace(" ", "")
    assert '"prompt":"hi"' in body.replace(" ", "")


@respx.mock
async def test_submit_task_429_raises_too_many():
    respx.post("http://agent-c-abc:8080/tasks").mock(return_value=httpx.Response(429))
    req = build_shim_request(
        task_id="tsk_1",
        body=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="claude-opus-4-7"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=100, timeout_seconds=30),
        credential="sk-x",
    )
    from control_plane.shim_client import ShimTooManyTasks

    async with _client() as c:
        with pytest.raises(ShimTooManyTasks):
            await c.submit_task(req)


@respx.mock
async def test_readyz_true_on_200():
    respx.get("http://agent-c-abc:8080/readyz").mock(return_value=httpx.Response(200))
    async with _client() as c:
        assert await c.readyz() is True


@respx.mock
async def test_delete_file_issues_delete_with_auth_and_path():
    route = respx.delete("http://agent-c-abc:8080/files/raw").mock(
        return_value=httpx.Response(204)
    )
    async with _client() as c:
        await c.delete_file("notes/todo.txt")
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sekret"
    assert sent.url.params["path"] == "notes/todo.txt"


@respx.mock
async def test_delete_file_raises_on_error_status():
    respx.delete("http://agent-c-abc:8080/files/raw").mock(
        return_value=httpx.Response(404)
    )
    async with _client() as c:
        with pytest.raises(httpx.HTTPStatusError):
            await c.delete_file("missing.txt")

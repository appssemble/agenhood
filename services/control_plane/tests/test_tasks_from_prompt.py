from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import control_plane.routers.tasks as tasks_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal
from control_plane.config import Settings
from control_plane.errors import api_error
from control_plane.routers.containers import _principal, _session

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed", seed_api_key="tk_live_seed", seed_llm_api_key="",
    agent_image_tag="test", internal_network="test",
    readyz_timeout_seconds=1.0, shim_port=8080,
)
_APP = create_app(_SETTINGS)
TENANT = "ten_1"


def _principal_override() -> Principal:
    return Principal(tenant_id=TENANT, role="member", is_staff=False, user_id=None)


class _DummySession:
    pass


def _override_auth():
    _APP.dependency_overrides[_principal] = _principal_override
    _APP.dependency_overrides[_session] = lambda: _DummySession()


@pytest.mark.asyncio
async def test_from_prompt_resolves_and_submits(monkeypatch):
    captured: dict = {}

    async def fake_load_prompt(session, tenant_id, pid):
        assert tenant_id == TENANT and pid == "prm_abc"
        return {"body": "Hi {{name}}", "variables": [{"name": "name", "default": "there"}]}

    async def fake_core(session, **kw):
        captured.update(kw)
        return {"task_id": "tsk_1", "status": "running"}

    monkeypatch.setattr(tasks_mod, "_load_prompt", fake_load_prompt)
    monkeypatch.setattr(tasks_mod, "submit_task_core", fake_core)
    _override_auth()
    try:
        async with AsyncClient(transport=ASGITransport(app=_APP), base_url="http://t") as c:
            r = await c.post(
                "/v1/containers/con_1/tasks/from-prompt",
                json={"prompt_id": "prm_abc", "variables": {"name": "Ada"}},
            )
        assert r.status_code == 200
        assert r.json()["task_id"] == "tsk_1"
        body = captured["body"]
        assert body.prompt == "Hi Ada"
        assert body.metadata["prompt_id"] == "prm_abc"
        assert body.effort is None
        assert captured["cid"] == "con_1"
        assert captured["tenant_id"] == TENANT
    finally:
        _APP.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_from_prompt_carries_effort_override(monkeypatch):
    captured: dict = {}

    async def fake_load_prompt(session, tenant_id, pid):
        return {"body": "Hi {{name}}", "variables": [{"name": "name", "default": "there"}]}

    async def fake_core(session, **kw):
        captured.update(kw)
        return {"task_id": "tsk_1", "status": "running"}

    monkeypatch.setattr(tasks_mod, "_load_prompt", fake_load_prompt)
    monkeypatch.setattr(tasks_mod, "submit_task_core", fake_core)
    _override_auth()
    try:
        async with AsyncClient(transport=ASGITransport(app=_APP), base_url="http://t") as c:
            r = await c.post(
                "/v1/containers/con_1/tasks/from-prompt",
                json={"prompt_id": "prm_abc", "variables": {"name": "Ada"}, "effort": "low"},
            )
        assert r.status_code == 200
        assert captured["body"].effort == "low"
    finally:
        _APP.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_from_prompt_404_when_prompt_missing(monkeypatch):
    async def fake_load_prompt(session, tenant_id, pid):
        raise api_error(404, "prompt_not_found", "prompt not found", "prompt_id")

    async def fake_core(session, **kw):  # must not run
        raise AssertionError("submit_task_core should not be called")

    monkeypatch.setattr(tasks_mod, "_load_prompt", fake_load_prompt)
    monkeypatch.setattr(tasks_mod, "submit_task_core", fake_core)
    _override_auth()
    try:
        async with AsyncClient(transport=ASGITransport(app=_APP), base_url="http://t") as c:
            r = await c.post(
                "/v1/containers/con_1/tasks/from-prompt",
                json={"prompt_id": "prm_missing"},
            )
        assert r.status_code == 404
        assert "prompt_not_found" in r.text
    finally:
        _APP.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_from_prompt_requires_prompt_id(monkeypatch):
    _override_auth()
    try:
        async with AsyncClient(transport=ASGITransport(app=_APP), base_url="http://t") as c:
            r = await c.post("/v1/containers/con_1/tasks/from-prompt", json={})
        assert r.status_code == 422  # pydantic: prompt_id required
    finally:
        _APP.dependency_overrides.clear()

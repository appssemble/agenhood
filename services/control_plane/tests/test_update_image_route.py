from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.containers as containers_mod
from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="dev",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)
_APP = create_app(_SETTINGS)
# Principal fields: tenant_id, role, is_staff, user_id
_PRINCIPAL = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)
CID = "ctr_1"


class _FakeSession:
    async def commit(self) -> None:
        pass


def _client(monkeypatch) -> TestClient:
    async def fake_loader(session, tenant_id, cid):
        return object()

    async def fake_limits(session, tid):
        return {"max_running_containers": 5}

    monkeypatch.setattr(containers_mod, "_load_owned_container", fake_loader)
    monkeypatch.setattr(containers_mod, "load_tenant_limits", fake_limits)

    async def fake_session_dep() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    _APP.dependency_overrides[containers_mod._session] = fake_session_dep
    return TestClient(_APP, raise_server_exceptions=False)


def teardown_function() -> None:
    _APP.dependency_overrides.clear()


def test_update_image_happy_path(monkeypatch) -> None:
    seen: dict = {}

    async def fake_update(db, dc, shim, cid, tid, tag, **kw):
        seen["args"] = (cid, tid, tag, kw.get("limit"))

    async def fake_status(db, cid):
        return "running"

    monkeypatch.setattr(containers_mod.lifecycle, "update_image", fake_update)
    monkeypatch.setattr(containers_mod.lifecycle, "current_status", fake_status)
    client = _client(monkeypatch)
    r = client.post(f"/v1/containers/{CID}/update-image", json={"image_tag": "v2"})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": CID, "status": "running", "image_tag": "v2"}
    assert seen["args"] == (CID, "ten_1", "v2", 5)


def test_update_image_blank_tag_rejected(monkeypatch) -> None:
    client = _client(monkeypatch)
    r = client.post(f"/v1/containers/{CID}/update-image", json={"image_tag": "   "})
    # validation_error() maps to APIError(400, ...) in control_plane/errors.py
    assert r.status_code == 400

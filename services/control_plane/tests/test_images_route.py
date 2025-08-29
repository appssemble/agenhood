from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.images as images_mod
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
_PRINCIPAL = Principal(tenant_id="ten_1", role="member", is_staff=False, user_id=None)


def test_list_image_tags_ok(monkeypatch) -> None:
    async def fake_list(settings, docker_client):
        return {
            "tags": [{"tag": "v1", "source": "registry"}, {"tag": "dev", "source": "local"}],
            "default_tag": "dev",
            "registry_unavailable": False,
        }

    monkeypatch.setattr(images_mod.registry, "list_image_tags", fake_list)
    _APP.dependency_overrides[resolve_principal] = lambda: _PRINCIPAL
    try:
        client = TestClient(_APP, raise_server_exceptions=False)
        r = client.get("/v1/images/tags")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["default_tag"] == "dev"
        assert {t["tag"] for t in body["tags"]} == {"v1", "dev"}
        assert body["registry_unavailable"] is False
    finally:
        _APP.dependency_overrides.clear()

import pytest
from httpx import ASGITransport, AsyncClient

from control_plane.app import create_app
from control_plane.auth.principal import Principal, resolve_principal
from control_plane.config import Settings

pytestmark = pytest.mark.unit

_FAKE_PRINCIPAL = Principal(tenant_id="ten_seed", role="member", is_staff=False, user_id=None)


async def test_create_with_unknown_driver_returns_validation_error(monkeypatch):
    s = Settings.from_env()
    app = create_app(s)

    # Override resolve_principal so no DB is needed in this unit test.
    app.dependency_overrides[resolve_principal] = lambda: _FAKE_PRINCIPAL

    # Force the seed-tenant limits lookup to a known dict without a DB by stubbing
    # the helper the router uses.
    import control_plane.routers.containers as mod

    async def fake_load_tenant_limits(session, tenant_id):
        return {"allowed_drivers": ["vanilla"], "allowed_models": ["claude-opus-4-7"]}

    monkeypatch.setattr(mod, "load_tenant_limits", fake_load_tenant_limits)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/v1/containers",
            json={
                "name": "c1",
                "config": {"driver": "nope", "model": "claude-opus-4-7"},
            },
        )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["field"] == "driver"

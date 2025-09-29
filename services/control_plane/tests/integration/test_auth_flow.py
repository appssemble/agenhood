"""Integration tests for the auth flow (Task 20).

Verifies:
- POST /v1/auth/login sets an HttpOnly cookie and returns user info.
- Authenticated requests succeed with the cookie jar.
- API-key auth works for the machine path.
- Session-only routes (users) are blocked with API keys (403).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_ADMIN_AUTH = {"Authorization": "Bearer boot-test-key"}


async def _bootstrap_tenant(client: AsyncClient, *, suffix: str = "auth") -> dict:
    """Create a tenant + owner via the bootstrap admin key."""
    r = await client.post(
        "/admin/v1/tenants",
        headers=_ADMIN_AUTH,
        json={
            "name": f"Acme-{suffix}",
            "limits": {},
            "owner": {
                "email": f"owner-{suffix}@acme.example.com",
                "name": "Owner",
                "password": "pw-initial",
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_login_sets_cookie_and_me_succeeds(app_with_admin_key: object) -> None:
    """Login returns a JSON body with role/must_change_password and sets
    an HttpOnly agent_session cookie; subsequent GET /v1/auth/me succeeds."""
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="cookie")
        r = await client.post(
            "/v1/auth/login",
            json={"email": "owner-cookie@acme.example.com", "password": "pw-initial"},
        )
        assert r.status_code == 200, r.text
        # Session cookie must be present and marked HttpOnly.
        assert "agent_session" in r.cookies, f"cookies={dict(r.cookies)}"
        body = r.json()
        assert body["role"] == "owner", body
        assert body["must_change_password"] is True, body

        # Authenticated request using the cookie jar (httpx carries it automatically).
        me = await client.get("/v1/auth/me")
        assert me.status_code == 200, me.text
        assert me.json()["role"] == "owner", me.json()


async def test_login_wrong_password_returns_401(app_with_admin_key: object) -> None:
    """Wrong password must return 401, not 500."""
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="badpw")
        r = await client.post(
            "/v1/auth/login",
            json={"email": "owner-badpw@acme.example.com", "password": "WRONG"},
        )
        assert r.status_code == 401, r.text


async def test_api_key_auth_drives_machine_path(app_with_admin_key: object) -> None:
    """An API key minted by an owner authenticates successfully (principal=api_key)
    and is blocked from session-only routes like GET /v1/users (403)."""
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        await _bootstrap_tenant(client, suffix="apikey")
        # Login to create an owner session.
        await client.post(
            "/v1/auth/login",
            json={"email": "owner-apikey@acme.example.com", "password": "pw-initial"},
        )
        # Owner mints an API key (one-time reveal).
        k = await client.post("/v1/api-keys", json={"name": "ci"})
        assert k.status_code == 201, k.text
        secret = k.json()["key"]
        assert secret.startswith("tk_live_"), secret

        # Fresh client (no cookie) authenticates with the API key.
        async with AsyncClient(transport=transport, base_url="https://t") as machine:
            me = await machine.get(
                "/v1/auth/me",
                headers={"Authorization": f"Bearer {secret}"},
            )
            assert me.status_code == 200, me.text
            assert me.json()["principal"] == "api_key", me.json()

            # Session-only routes must be blocked for API-key principals.
            denied = await machine.get(
                "/v1/users",
                headers={"Authorization": f"Bearer {secret}"},
            )
            assert denied.status_code == 403, denied.text


async def test_unauthenticated_request_returns_401(app_with_admin_key: object) -> None:
    """A request with no token and no cookie must return 401."""
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://t") as client:
        r = await client.get("/v1/auth/me")
        assert r.status_code == 401, r.text

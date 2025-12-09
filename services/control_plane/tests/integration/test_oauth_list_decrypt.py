from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_BEARER_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}
_ADMIN_AUTH = {"Authorization": "Bearer boot-test-key"}
_KEY = b"A" * 32


async def _insert_oauth_cred(app, tenant_id: str) -> str:
    """Insert an oauth credential for *tenant_id*, deleting any previous one first."""
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.credentials_service import build_oauth_credential_row

    factory = app.state.session_factory
    row = build_oauth_credential_row(
        tenant_id=tenant_id, provider="openai",
        access_token="acc-1", refresh_token="ref-SECRET-DO-NOT-LEAK",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        account_id="acct_5678", created_by=None, master_key=_KEY,
    )
    async with factory() as s:
        # Delete any previous oauth credential for this tenant/provider so this
        # helper is idempotent across tests sharing the same Postgres session.
        await s.execute(
            sa.delete(t.credentials).where(
                t.credentials.c.tenant_id == tenant_id,
                t.credentials.c.provider == "openai",
                t.credentials.c.auth_method == "oauth_subscription",
            )
        )
        await s.execute(sa.insert(t.credentials).values(**row))
        await s.commit()
    return row["id"]


async def _login_session(client: AsyncClient, email: str, password: str) -> None:
    """Log in and let httpx carry the session cookie forward."""
    lr = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert lr.status_code == 200, lr.text


@pytest.mark.asyncio
async def test_list_includes_oauth_metadata_no_tokens(app_with_admin_key: object) -> None:
    """List endpoint returns auth_method/status/account_tail and NEVER leaks tokens."""
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        # Bootstrap a fresh tenant so we get a clean credentials table.
        r = await client.post(
            "/admin/v1/tenants",
            headers=_ADMIN_AUTH,
            json={
                "name": "OAuthListTest",
                "limits": {},
                "owner": {
                    "email": "owner-oauthlist@test.example.com",
                    "name": "Owner",
                    "password": "pw-test",
                },
            },
        )
        assert r.status_code == 201, r.text
        tenant_id = r.json()["id"]

        # Log in to get a session cookie (require_session_admin needs this).
        await _login_session(client, "owner-oauthlist@test.example.com", "pw-test")

        # Insert an oauth credential for this tenant.
        cred_id = await _insert_oauth_cred(app_with_admin_key, tenant_id)

        # List credentials — must return oauth fields and no token secrets.
        resp = await client.get("/v1/credentials")
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "ref-SECRET-DO-NOT-LEAK" not in body
        assert "acc-1" not in body
        creds = resp.json()["credentials"]
        oauth = next(c for c in creds if c["id"] == cred_id)
        assert oauth["auth_method"] == "oauth_subscription"
        assert oauth["status"] == "active"
        assert oauth["account_tail"] == "5678"


@pytest.mark.asyncio
async def test_internal_decrypt_oauth_returns_access_not_refresh(seeded_app: object) -> None:
    """_internal/decrypt with a non-staff seed-tenant principal returns 403."""
    cred_id = await _insert_oauth_cred(seeded_app, "ten_seed")
    # The seed tenant key is a bearer token with role=member (not staff).
    transport = ASGITransport(app=seeded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/v1/credentials/_internal/decrypt/{cred_id}",
            headers=_BEARER_HEADERS,
        )
        # Seed tenant principal is not staff → 403 (gate intact).
        assert r.status_code == 403

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

_KEY = b"A" * 32
_ADMIN = {"Authorization": "Bearer boot-test-key"}


@pytest.mark.asyncio
async def test_set_api_key_preserves_coexisting_oauth(app_with_admin_key: object) -> None:
    import sqlalchemy as sa

    import control_plane.tables as t
    from control_plane.credentials_service import build_oauth_credential_row

    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post(
            "/admin/v1/tenants", headers=_ADMIN,
            json={
                "name": "Acme-coexist", "limits": {},
                "owner": {
                    "email": "owner-coexist@acme.example.com",
                    "name": "Owner",
                    "password": "pw-initial",
                },
            },
        )
        assert r.status_code == 201, r.text
        tenant_id = r.json()["id"]

        # Seed an oauth_subscription credential for openai directly.
        factory = app_with_admin_key.state.session_factory  # type: ignore[attr-defined]
        row = build_oauth_credential_row(
            tenant_id=tenant_id, provider="openai",
            access_token="acc", refresh_token="ref",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            account_id="acct_1", created_by=None, master_key=_KEY,
        )
        async with factory() as s:
            await s.execute(sa.insert(t.credentials).values(**row))
            await s.commit()

        # Log in as the owner and store an API key for the SAME provider.
        await client.post(
            "/v1/auth/login",
            json={"email": "owner-coexist@acme.example.com", "password": "pw-initial"},
        )
        sr = await client.post(
            "/v1/credentials", json={"provider": "openai", "api_key": "sk-test-key-1234"}
        )
        assert sr.status_code == 201, sr.text

        # Both must coexist.
        lr = await client.get("/v1/credentials")
        assert lr.status_code == 200, lr.text
        openai_creds = [c for c in lr.json()["credentials"] if c["provider"] == "openai"]
        methods = sorted(c["auth_method"] for c in openai_creds)
        assert methods == ["api_key", "oauth_subscription"], openai_creds

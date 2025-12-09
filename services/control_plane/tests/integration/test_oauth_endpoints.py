from __future__ import annotations

import os

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_ADMIN_AUTH = {"Authorization": "Bearer boot-test-key"}


async def _login(client: AsyncClient, suffix: str) -> None:
    """Bootstrap a tenant + owner via the admin key, then log in (session cookie)."""
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
    lr = await client.post(
        "/v1/auth/login",
        json={"email": f"owner-{suffix}@acme.example.com", "password": "pw-initial"},
    )
    assert lr.status_code == 200, lr.text


@respx.mock
@pytest.mark.asyncio
async def test_start_creates_pending_connection(app_with_admin_key: object) -> None:
    from control_plane.config import Settings

    s = Settings.from_env()
    respx.post(s.openai_oauth_device_code_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_auth_id": "da_1",
                "user_code": "ABCD-1234",
                "interval": "5",
                "expires_at": "2030-01-01T00:00:00+00:00",
            },
        )
    )
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "start")
        r = await client.post(
            "/v1/credentials/oauth/openai/start",
            json={"tos_acknowledged": True},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["user_code"] == "ABCD-1234"
        assert body["connection_id"].startswith("oac_")

        st = await client.get(
            f"/v1/credentials/oauth/openai/connections/{body['connection_id']}",
        )
        assert st.status_code == 200
        assert st.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_start_requires_tos_ack(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "tos")
        r = await client.post(
            "/v1/credentials/oauth/openai/start",
            json={"tos_acknowledged": False},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "tos_required"

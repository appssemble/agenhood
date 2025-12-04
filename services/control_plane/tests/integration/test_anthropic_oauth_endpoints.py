from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

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
    r = await client.post(
        "/admin/v1/tenants", headers=_ADMIN_AUTH,
        json={"name": f"Acme-{suffix}", "limits": {},
              "owner": {"email": f"o-{suffix}@acme.example.com", "name": "O", "password": "pw"}},
    )
    assert r.status_code == 201, r.text
    lr = await client.post("/v1/auth/login",
                           json={"email": f"o-{suffix}@acme.example.com", "password": "pw"})
    assert lr.status_code == 200, lr.text


@pytest.mark.asyncio
async def test_start_returns_authorize_url(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "astart")
        r = await client.post("/v1/credentials/oauth/anthropic/start",
                              json={"tos_acknowledged": True})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["connection_id"].startswith("oac_")
        assert body["authorize_url"].startswith("https://claude.ai/oauth/authorize?")
        assert "code_challenge=" in body["authorize_url"]


@respx.mock
@pytest.mark.asyncio
async def test_complete_stores_credential(app_with_admin_key: object) -> None:
    from control_plane.config import Settings

    s = Settings.from_env()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(200, json={
            "access_token": "sk-ant-oat01-x", "refresh_token": "sk-ant-ort01-y",
            "expires_in": 28800, "account": {"uuid": "acct-9"},
        })
    )
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "acomplete")
        start = (await client.post("/v1/credentials/oauth/anthropic/start",
                                   json={"tos_acknowledged": True})).json()
        state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
        r = await client.post(
            "/v1/credentials/oauth/anthropic/complete",
            json={"connection_id": start["connection_id"], "code": f"the-code#{state}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "connected"
        assert body["credential_id"]
        # the credential now shows up as an anthropic subscription
        creds = (await client.get("/v1/credentials")).json()["credentials"]
        assert any(c["provider"] == "anthropic" and c["auth_method"] == "oauth_subscription"
                   for c in creds)


@respx.mock
@pytest.mark.asyncio
async def test_complete_failed_exchange_marks_failed(app_with_admin_key: object) -> None:
    from control_plane.config import Settings

    s = Settings.from_env()
    respx.post(s.anthropic_oauth_token_url).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "afail")
        start = (await client.post("/v1/credentials/oauth/anthropic/start",
                                   json={"tos_acknowledged": True})).json()
        r = await client.post("/v1/credentials/oauth/anthropic/complete",
                              json={"connection_id": start["connection_id"], "code": "bad"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_complete_state_mismatch_rejected(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "amismatch")
        start = (await client.post("/v1/credentials/oauth/anthropic/start",
                                   json={"tos_acknowledged": True})).json()
        r = await client.post(
            "/v1/credentials/oauth/anthropic/complete",
            json={"connection_id": start["connection_id"], "code": "the-code#wrong-state"})
        assert r.status_code == 400
        assert "state" in r.text


@pytest.mark.asyncio
async def test_complete_kill_switch_rejected(app_with_admin_key: object) -> None:
    import dataclasses

    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "akill")
        # Start while the kill switch is off so a pending connection exists...
        start = (await client.post("/v1/credentials/oauth/anthropic/start",
                                   json={"tos_acknowledged": True})).json()
        # ...then flip the kill switch and confirm complete is refused.
        app_with_admin_key.state.settings = dataclasses.replace(  # type: ignore[attr-defined]
            app_with_admin_key.state.settings,  # type: ignore[attr-defined]
            oauth_subscription_kill_switch=True,
        )
        try:
            r = await client.post("/v1/credentials/oauth/anthropic/complete",
                                  json={"connection_id": start["connection_id"], "code": "x"})
            assert r.status_code == 400, r.text
            assert "oauth_disabled" in r.text
        finally:
            app_with_admin_key.state.settings = dataclasses.replace(  # type: ignore[attr-defined]
                app_with_admin_key.state.settings,  # type: ignore[attr-defined]
                oauth_subscription_kill_switch=False,
            )


@respx.mock
@pytest.mark.asyncio
async def test_complete_wrong_provider_rejected(app_with_admin_key: object) -> None:
    from control_plane.config import Settings

    s = Settings.from_env()
    respx.post(s.openai_oauth_device_code_url).mock(
        return_value=httpx.Response(200, json={
            "device_auth_id": "da_1", "user_code": "ABCD-1234",
            "interval": "5", "expires_at": "2030-01-01T00:00:00+00:00",
        })
    )
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "awrongprov")
        # Create an OpenAI connection, then try to finish it via the Anthropic route.
        start = (await client.post("/v1/credentials/oauth/openai/start",
                                   json={"tos_acknowledged": True})).json()
        r = await client.post("/v1/credentials/oauth/anthropic/complete",
                              json={"connection_id": start["connection_id"], "code": "x"})
        assert r.status_code == 400, r.text
        assert "wrong_provider" in r.text

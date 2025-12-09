from __future__ import annotations

import os

import pytest
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
async def test_providers_derived_from_catalog(app_with_admin_key: object) -> None:
    transport = ASGITransport(app=app_with_admin_key)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _login(client, "provs")
        r = await client.get("/v1/credentials/providers")
        assert r.status_code == 200, r.text
        providers = r.json()["providers"]
        by_id = {p["id"]: p["label"] for p in providers}
        # The catalog has api-key models for both anthropic and openai.
        assert by_id.get("anthropic") == "Anthropic"
        assert by_id.get("openai") == "OpenAI"
        # Keyless/free providers (e.g. opencode) are NOT api-key providers.
        assert "opencode" not in by_id
        # Sorted by id, no duplicates.
        ids = [p["id"] for p in providers]
        assert ids == sorted(set(ids))

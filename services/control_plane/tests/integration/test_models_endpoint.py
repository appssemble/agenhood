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

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}


@pytest.mark.asyncio
async def test_models_endpoint_badges_by_credentials(seeded_app: object) -> None:
    # seeded_app's seed tenant has an anthropic api_key (from the integration conftest).
    transport = ASGITransport(app=seeded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/models", headers=_HEADERS)
        assert r.status_code == 200, r.text
        models = {m["id"]: m for m in r.json()["models"]}
        # At least the free Zen models are present and usable.
        free = [m for m in models.values() if m["category"] == "free"]
        assert free and all(m["available"] for m in free)
        # Anthropic models are usable (seed tenant has an anthropic key).
        ant = [m for m in models.values() if m["provider"] == "anthropic"]
        if ant:
            assert all(m["available"] for m in ant)
        # OpenAI api models (no openai key on the seed tenant) require a credential.
        oai = [
            m for m in models.values()
            if m["provider"] == "openai" and m["category"] == "api_key"
        ]
        if oai:
            assert all(not m["available"] and "openai_api_key" in m["requires"] for m in oai)


@pytest.mark.asyncio
async def test_models_endpoint_driver_filter_vanilla(seeded_app: object) -> None:
    transport = ASGITransport(app=seeded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/models?driver=vanilla", headers=_HEADERS)
        assert r.status_code == 200
        providers = {m["provider"] for m in r.json()["models"]}
        assert providers <= {"anthropic"}  # vanilla → anthropic only

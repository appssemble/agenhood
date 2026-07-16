"""Integration: vanilla driver runs OpenAI and opencode-go models end-to-end.

Verifies the multi-provider design: an ``openai`` credential drives a bare
``gpt-*`` model over the chat-completions stub endpoint (Bearer auth), and an
``opencode`` credential drives an ``opencode-go/*`` model (credential aliasing
+ per-family protocol routing), both through the standard event stream to a
completed task.
"""
from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}


async def _add_credential(app_settings, provider: str, api_key: str) -> None:
    """Insert an extra credential row for the seed tenant (the seeded_app
    fixture only seeds anthropic)."""
    from control_plane.credentials_service import build_credential_row
    from control_plane.db import make_engine, make_session_factory
    from control_plane.tables import credentials

    from .conftest import _TEST_MASTER_KEY

    row = build_credential_row(
        tenant_id=app_settings.seed_tenant_id, provider=provider,
        api_key=api_key, created_by=None, master_key=_TEST_MASTER_KEY,
    )
    engine = make_engine(app_settings)
    factory = make_session_factory(engine)
    async with factory() as s:
        await s.execute(
            sa.delete(credentials).where(
                credentials.c.tenant_id == app_settings.seed_tenant_id,
                credentials.c.provider == provider,
            )
        )
        await s.execute(sa.insert(credentials).values(**row))
        await s.commit()
    await engine.dispose()


async def _run_vanilla_task(app, model: str) -> str:
    """Create a vanilla container on ``model``, run one task to a terminal
    status, tear down, and return the terminal status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/containers", headers=_HEADERS,
            json={"name": f"mp-{model.replace('/', '-').replace('.', '-')}",
                  "config": {"driver": "vanilla", "model": model,
                             "tools": ["read_file", "write_file"]}},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            ts = await client.post(
                f"/v1/containers/{cid}/tasks", headers=_HEADERS,
                json={"prompt": "write out.txt then finish",
                      "output": {"type": "structured",
                                 "schema": {"type": "object",
                                            "required": ["value"],
                                            "properties": {"value": {"type": "integer"}}}}},
            )
            assert ts.status_code == 200, ts.text
            tid = ts.json()["task_id"]

            terminal = None
            sse_headers = {**_HEADERS, "Accept": "text/event-stream"}
            async with client.stream(
                "GET", f"/v1/containers/{cid}/tasks/{tid}/events",
                headers=sse_headers, timeout=90,
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[len("data:"):].strip())
                    if ev["type"] == "status_change" and ev["payload"].get("to") in (
                        "completed", "failed", "timed_out", "cancelled",
                    ):
                        terminal = ev["payload"]["to"]
                        break
            return terminal
        finally:
            await client.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)


async def test_vanilla_runs_openai_model_with_bearer_key(
    seeded_app, stub_llm_host_url, app_settings,
) -> None:
    await _add_credential(app_settings, "openai", "stub-openai-key")

    terminal = await _run_vanilla_task(seeded_app, "gpt-4o-mini")
    assert terminal == "completed"

    # The decrypted openai key arrived as a Bearer header at the
    # chat-completions endpoint.
    async with httpx.AsyncClient() as hx:
        resp = await hx.get(f"{stub_llm_host_url}/_test/last_auth_header", timeout=10)
    received = resp.json().get("auth_header")
    assert received == "Bearer stub-openai-key"


async def test_vanilla_runs_opencode_go_model_via_alias(
    seeded_app, stub_llm_host_url, app_settings,
) -> None:
    # The Go plan uses the tenant's *opencode* credential row (alias).
    await _add_credential(app_settings, "opencode", "stub-opencode-key")

    # chat-completions family (glm) — Bearer auth.
    terminal = await _run_vanilla_task(seeded_app, "opencode-go/glm-5.2")
    assert terminal == "completed"
    async with httpx.AsyncClient() as hx:
        resp = await hx.get(f"{stub_llm_host_url}/_test/last_auth_header", timeout=10)
    assert resp.json().get("auth_header") == "Bearer stub-opencode-key"

    # anthropic-compatible family (minimax) — x-api-key auth on /v1/messages.
    terminal = await _run_vanilla_task(seeded_app, "opencode-go/minimax-m3")
    assert terminal == "completed"
    async with httpx.AsyncClient() as hx:
        resp = await hx.get(f"{stub_llm_host_url}/_test/last_auth_header", timeout=10)
    assert resp.json().get("auth_header") == "stub-opencode-key"

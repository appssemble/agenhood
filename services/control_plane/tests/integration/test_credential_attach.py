"""Integration test: stored credential reaches the stub LLM but not the DB.

Verifies spec §4.5: the decrypted API key is injected at task-submit time and
forwarded to the LLM adapter; it MUST NOT appear in the persisted task body or
config_snapshot in the database.

This test uses:
  - ``seeded_app``       — the app with the seed tenant that has a pre-seeded
                           anthropic credential (value "stub-key").
  - ``stub_llm_host_url``— the host-reachable URL of the stub LLM container,
                           used to query /_test/last_auth_header after the task
                           completes.
  - ``app_settings``     — needed to open a raw DB connection and verify the
                           persisted task row is clean.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}
_SECRET = "stub-key"   # value seeded by the fixture into the credentials table


async def _wait_for_stub_llm(host_url: str, max_wait: float = 30.0) -> None:
    """Block until the stub LLM container is accepting connections."""
    deadline = asyncio.get_event_loop().time() + max_wait
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{host_url}/docs", timeout=2.0)
                if r.status_code < 500:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Stub LLM at {host_url} did not become ready within {max_wait}s")


async def test_stored_credential_reaches_stub_llm_but_not_db(
    seeded_app: object,
    stub_llm_host_url: str,
    app_settings: object,
) -> None:
    """Submit a task on the seed tenant; assert:

    1. The stub LLM received the DECRYPTED credential in its x-api-key header.
    2. The persisted task row's ``body`` and ``config_snapshot`` columns contain
       no trace of the secret.
    """
    # Wait for the stub LLM to be ready (it may still be starting).
    await _wait_for_stub_llm(stub_llm_host_url)

    transport = ASGITransport(app=seeded_app)
    tid: str | None = None
    cid: str | None = None

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a container with the vanilla driver.
        r = await client.post(
            "/v1/containers",
            headers=_HEADERS,
            json={
                "name": "cred-attach-test",
                "config": {
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "tools": ["read_file", "write_file"],
                },
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

        try:
            # Submit a task. The vanilla driver will call the stub LLM with the
            # decrypted credential injected as x-api-key.
            ts = await client.post(
                f"/v1/containers/{cid}/tasks",
                headers=_HEADERS,
                json={
                    "prompt": "write out.txt then finish",
                    "output": {
                        "type": "structured",
                        "schema": {
                            "type": "object",
                            "required": ["value"],
                            "properties": {"value": {"type": "integer"}},
                        },
                    },
                },
            )
            assert ts.status_code == 200, ts.text
            tid = ts.json()["task_id"]

            # Drain the SSE stream until we see a terminal status_change.
            sse_headers = {**_HEADERS, "Accept": "text/event-stream"}
            async with client.stream(
                "GET",
                f"/v1/containers/{cid}/tasks/{tid}/events",
                headers=sse_headers,
                timeout=90,
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[len("data:"):].strip())
                    if ev["type"] == "status_change" and ev["payload"].get("to") in (
                        "completed", "failed", "timed_out", "cancelled",
                    ):
                        break

            # -------------------------------------------------------------------
            # 1. Verify the persisted task row has NO trace of the secret.
            #    Must run BEFORE teardown — DELETE now hard-purges task rows too.
            # -------------------------------------------------------------------
            assert tid is not None, "Task was never submitted"
            from control_plane.db import make_engine, make_session_factory

            engine = make_engine(app_settings)  # type: ignore[arg-type]
            factory = make_session_factory(engine)
            async with factory() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT body::text AS b, config_snapshot::text AS c"
                            " FROM tasks WHERE id=:i"
                        ),
                        {"i": tid},
                    )
                ).mappings().first()
            await engine.dispose()

            assert row is not None, f"No task row found for id={tid}"
            assert _SECRET not in row["b"], (
                f"Secret {_SECRET!r} found in task body column — credential leaked into DB!"
            )
            assert _SECRET not in row["c"], (
                f"Secret {_SECRET!r} found in config_snapshot column — credential leaked into DB!"
            )

        finally:
            if cid:
                await client.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)

    # -----------------------------------------------------------------------
    # 2. Verify the stub LLM received the DECRYPTED credential.
    #    The stub LLM is a separate container that retains the recorded header
    #    even after the agent container is deleted.
    # -----------------------------------------------------------------------
    async with httpx.AsyncClient() as hx:
        resp = await hx.get(f"{stub_llm_host_url}/_test/last_auth_header", timeout=10)
    resp.raise_for_status()
    received = resp.json().get("auth_header")
    assert received is not None, (
        "Stub LLM did not record any auth header — "
        "the credential may not have been forwarded"
    )
    assert _SECRET in received, (
        f"Decrypted credential {_SECRET!r} not found in stub LLM auth header {received!r}"
    )

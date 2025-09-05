"""Integration test: two open SSE streams must not exhaust the DB pool.

Incident: sse-db-pool-exhaustion-incident
Root cause: stream_events in routers/tasks.py took `session: AsyncSession =
Depends(_session)`.  For a StreamingResponse FastAPI keeps the Depends yield-
context open for the whole stream lifetime, so EACH open stream pins one pooled
connection.  With pool_size=2 and two viewers, /healthz (which needs a session
for SELECT 1) can't get a connection and times out.

This test:
  - configures the engine with pool_size=2, max_overflow=0
  - opens two concurrent SSE streams (held open via _BlockingShim)
  - asserts /healthz still returns 200

RED  → current code (Depends pins the session for stream lifetime)
GREEN → after fix (session.close() called before the stream generator runs)
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import control_plane.routers.tasks as tasksmod
from control_plane.app import create_app
from control_plane.config import Settings
from control_plane.models_db import containers, tasks
from control_plane.seed import apply_seed

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_HDR = {"Authorization": "Bearer tk_live_seedkey"}
_SSE = {**_HDR, "Accept": "text/event-stream"}
_CFG = {
    "driver": "vanilla",
    "model": "m",
    "system_prompt": "",
    "system_prompt_mode": "augment",
    "tools": [],
    "context": {"variables": {}, "text": None, "files": []},
}


class _BlockingShim:
    """Yields one event then blocks forever — emulates a long-running stream."""

    def __init__(self, *a, **k):
        pass

    async def stream_events(self, tid, after_seq):
        yield b'data: {"seq": 1, "type": "token_update", "payload": {}}\n'
        await asyncio.Event().wait()  # never completes

    async def aclose(self):
        return None


@pytest_asyncio.fixture
async def pool_settings(migrated_db: str):
    """Minimal Settings pointing at the testcontainers Postgres (no agent infra)."""
    return Settings(
        database_url=migrated_db,
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seedkey",
        seed_llm_api_key="stub-key",
        agent_image_tag="test",
        internal_network="agent-runtime-internal-test",
        readyz_timeout_seconds=60,
        shim_port=8080,
    )


@pytest.mark.asyncio
async def test_two_open_streams_do_not_starve_the_pool(pool_settings, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    # Tiny pool: 2 connections, no overflow.  Two open streams must NOT pin both.
    engine = create_async_engine(
        pool_settings.database_url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=3,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed tenant + a container + a task (all committed before streaming).
    async with factory() as s:
        await apply_seed(s, pool_settings)
        await s.execute(sa.insert(containers).values(
            id="con_sse",
            tenant_id="ten_seed",
            name="con_sse",
            docker_name="dn",
            volume_name="vol",
            shim_token="tok",
            image_tag="t",
            config=_CFG,
            status="running",
            created_at=datetime.now(UTC),
            status_changed_at=datetime.now(UTC),
        ))
        await s.execute(sa.insert(tasks).values(
            id="tk_sse",
            tenant_id="ten_seed",
            container_id="con_sse",
            driver="vanilla",
            model="m",
            body={"prompt": "p"},
            config_snapshot=_CFG,
            status="running",
            tokens_in=0,
            tokens_out=0,
            iterations_used=0,
            created_at=datetime.now(UTC),
        ))
        await s.commit()

    app = create_app(pool_settings)
    app.state.engine = engine
    app.state.session_factory = factory
    # Patch _shim_for so no real Docker/shim is needed.
    monkeypatch.setattr(tasksmod, "_shim_for", lambda settings, row: _BlockingShim())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:

        async def open_stream():
            """Start an SSE stream and return after receiving the first event,
            keeping the response context open so the stream stays alive."""
            async with client.stream(
                "GET",
                "/v1/containers/con_sse/tasks/tk_sse/events",
                headers=_SSE,
            ) as r:
                async for _ in r.aiter_raw():
                    return  # got first event; stay inside context manager

        # Hold TWO streams open — they must NOT pin the two pooled connections.
        s1 = asyncio.create_task(open_stream())
        s2 = asyncio.create_task(open_stream())
        await asyncio.sleep(0.5)

        # Pre-fix: each stream holds one of the 2 pool conns → healthz starves.
        # Post-fix: streams release the conn before looping → healthz gets 200.
        r = await asyncio.wait_for(client.get("/healthz"), timeout=5)
        assert r.status_code == 200, r.text

        for t in (s1, s2):
            t.cancel()

    await engine.dispose()

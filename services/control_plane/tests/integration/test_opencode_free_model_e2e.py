"""End-to-end API test: an opencode task on a free (keyless) model.

This is the missing integration coverage for the opencode path — it drives the
*whole* pipeline through the public HTTP API:

    create container (opencode + a free model)  →  POST /tasks  →  SSE /events
    →  terminal status_change  →  task result

It uses one of opencode's built-in free "Zen" models
(``opencode/deepseek-v4-flash-free``), so it needs **no LLM credential** — which
also exercises the keyless-provider path (the control plane must NOT reject the
submit with ``no_credential``). The agent container reaches opencode's free
service directly (the egress proxy is disabled on the test network).

Requires: docker, the agent image built with a working opencode (>= 1.x), and
outbound internet from the test container to opencode's free model service.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration]

FREE_MODEL = "opencode/deepseek-v4-flash-free"
TERMINAL = ("completed", "failed", "timed_out", "cancelled")


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def _allow_free_model(app_settings: object) -> None:
    """Add the free opencode model to the seed tenant's allowed_models so the
    container config validates. (Driver ``opencode`` is already allowed.)"""
    from control_plane.db import make_engine, make_session_factory
    from control_plane.tables import tenants

    engine = make_engine(app_settings)  # type: ignore[arg-type]
    factory = make_session_factory(engine)
    async with factory() as s:
        row = (
            await s.execute(sa.select(tenants).where(tenants.c.id == "ten_seed"))
        ).mappings().first()
        assert row is not None, "seed tenant missing"
        limits = dict(row["limits"])
        models = list(limits.get("allowed_models", []))
        if FREE_MODEL not in models:
            limits["allowed_models"] = [*models, FREE_MODEL]
            await s.execute(
                sa.update(tenants)
                .where(tenants.c.id == "ten_seed")
                .values(limits=limits)
            )
            await s.commit()
    await engine.dispose()


async def test_opencode_free_model_runs_through_the_api(
    seeded_app: object, app_settings: object
) -> None:
    await _allow_free_model(app_settings)
    headers = {"Authorization": "Bearer tk_live_seedkey"}

    async with await _client(seeded_app) as c:
        # 1. Create an opencode container on the free model. No credential is
        #    stored for the 'opencode' provider — this must still succeed.
        r = await c.post(
            "/v1/containers",
            headers=headers,
            json={
                "name": "opencode-e2e",
                "config": {
                    "driver": "opencode",
                    "model": FREE_MODEL,
                    "tools": [],  # opencode owns its tools
                },
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

        try:
            # 2. Submit a task. The keyless path means NO no_credential error.
            r = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
                json={
                    "prompt": "Reply with exactly one word: PONG",
                    "output": {"type": "text"},
                },
            )
            assert r.status_code == 200, r.text
            tid = r.json()["task_id"]

            # 3. Stream events; collect types + whether opencode actually ran.
            seen_types: list[str] = []
            saw_opencode_event = False
            terminal_to: str | None = None
            sse_headers = {**headers, "Accept": "text/event-stream"}
            async with c.stream(
                "GET",
                f"/v1/containers/{cid}/tasks/{tid}/events",
                headers=sse_headers,
                timeout=150,
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[len("data:"):].strip())
                    seen_types.append(ev["type"])
                    if ev["type"] in ("opencode_event", "opencode_stdout"):
                        saw_opencode_event = True
                    if ev["type"] == "status_change":
                        to = ev["payload"].get("to")
                        if to in TERMINAL:
                            terminal_to = to
                            break

            # 5. Poll the task to its terminal record.
            t = None
            for _ in range(60):
                t = (
                    await c.get(f"/v1/containers/{cid}/tasks/{tid}", headers=headers)
                ).json()
                if t["status"] in TERMINAL:
                    break
                await asyncio.sleep(1)
            assert t is not None

            # 4. The pipeline reached a terminal state ...
            assert terminal_to is not None, f"no terminal status; seen={seen_types}"
            # ... and opencode actually executed (NOT the opencode_unavailable
            #     fallback) — i.e. the bumped binary + new CLI invocation work.
            assert saw_opencode_event, (
                "opencode emitted no events — binary missing or invocation broken; "
                f"seen={seen_types}"
            )
            assert t["status"] != "failed" or "unavailable" not in json.dumps(
                t.get("error") or {}
            ), f"opencode unavailable — image not built with opencode? {t}"
            assert t["status"] == "completed", (
                f"opencode free-model task did not complete: status={t['status']} "
                f"error={t.get('error')}"
            )
            assert isinstance(t["result"]["output"], str) and t["result"]["output"], (
                f"expected non-empty text output, got {t['result']}"
            )
            # ... and per-task token usage was harvested from opencode's
            #     step_finish events (the driver translates them into cumulative
            #     token_update events). A completed run that produced text MUST
            #     have consumed input and output tokens — i.e. they are no longer
            #     stuck at the default 0.
            assert t["tokens_in"] > 0 and t["tokens_out"] > 0, (
                "opencode task completed but token usage was not recorded "
                f"(tokens_in={t['tokens_in']}, tokens_out={t['tokens_out']})"
            )
        finally:
            await c.request("DELETE", f"/v1/containers/{cid}", headers=headers)

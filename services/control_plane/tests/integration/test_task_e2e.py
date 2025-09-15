from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = [pytest.mark.integration]


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def _create_container(c: AsyncClient, headers: dict[str, str]) -> str:
    r = await c.post(
        "/v1/containers",
        headers=headers,
        json={
            "name": "e2e",
            "config": {
                "driver": "vanilla",
                "model": "claude-opus-4-7",
                "tools": ["read_file", "write_file"],
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_task_runs_streams_writes_file_and_persists_events(
    seeded_app: object, app_settings: object
) -> None:
    headers = {"Authorization": "Bearer tk_live_seedkey"}
    async with await _client(seeded_app) as c:
        cid = await _create_container(c, headers)
        try:
            # Submit a structured task; the stub LLM scripts write_file + done.
            r = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
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
            assert r.status_code == 200, r.text
            tid = r.json()["task_id"]
            assert r.json()["status"] == "running"

            # Stream events through the control-plane SSE proxy.
            # Must send Accept: text/event-stream to trigger the streaming path.
            seen_types: list[str] = []
            sse_headers = {
                **headers,
                "Accept": "text/event-stream",
            }
            async with c.stream(
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
                    seen_types.append(ev["type"])
                    if ev["type"] == "status_change" and ev["payload"].get("to") in (
                        "completed",
                        "failed",
                        "timed_out",
                        "cancelled",
                    ):
                        break
            assert "status_change" in seen_types, f"seen_types={seen_types}"

            # Poll the task to a terminal state and check the structured result.
            t = None
            for _ in range(60):
                resp2 = await c.get(f"/v1/containers/{cid}/tasks/{tid}", headers=headers)
                t = resp2.json()
                if t["status"] in ("completed", "failed", "timed_out", "cancelled"):
                    break
                await asyncio.sleep(1)
            assert t is not None
            assert t["status"] == "completed", t
            assert t["result"]["output"] == {"value": 42}, t

            # A file landed in the volume (proxied via the files API).
            files_resp = await c.get(f"/v1/containers/{cid}/files", headers=headers)
            files_resp.raise_for_status()
            paths = {f["path"] for f in files_resp.json()["files"]}
            assert "out.txt" in paths, f"files={paths}"

            # E2E download rung: fetch the file bytes through the control-plane
            # proxy (GET /files/raw), closing submit→stream→result→download.
            # The stub LLM writes out.txt with content "hello from stub".
            raw = await c.get(
                f"/v1/containers/{cid}/files/raw",
                headers=headers,
                params={"path": "out.txt"},
            )
            assert raw.status_code == 200, raw.text
            assert raw.content == b"hello from stub", (
                f"expected b'hello from stub', got {raw.content!r}"
            )

            # The events table received the forwarded copy.
            from control_plane.db import make_engine, make_session_factory
            from control_plane.models_db import events

            engine = make_engine(app_settings)  # type: ignore[arg-type]
            factory = make_session_factory(engine)
            async with factory() as s:
                rows = (
                    await s.execute(select(events).where(events.c.task_id == tid))
                ).all()
            await engine.dispose()
            assert len(rows) >= 1, "expected at least one event in the events table"
        finally:
            await c.request(
                "DELETE",
                f"/v1/containers/{cid}",
                headers=headers,
            )

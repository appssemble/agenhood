from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

pytestmark = [pytest.mark.integration]


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_second_task_over_cap_returns_429_and_no_orphan_row(
    seeded_app_cap1: object, app_settings: object
) -> None:
    headers = {"Authorization": "Bearer tk_live_seedkey"}
    async with await _client(seeded_app_cap1) as c:
        r = await c.post(
            "/v1/containers",
            headers=headers,
            json={
                "name": "cap",
                "config": {
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "tools": ["read_file", "write_file"],
                    # Embed SLOW in the system prompt so the stub LLM delays 5 s on
                    # turn 0, keeping the first task running when we submit the second.
                    "system_prompt": "SLOW",
                },
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            # First task occupies the single worker (stub LLM sleeps 5 s before
            # responding to the first /v1/messages call).
            a = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
                json={"prompt": "slow task"},
            )
            assert a.status_code == 200, a.text

            # Second task arrives immediately → shim 429 → control plane 429.
            b = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
                json={"prompt": "second task"},
            )
            assert b.status_code == 429, b.text
            assert b.json()["error"]["code"] == "too_many_tasks"

            # No orphan pending row: exactly one task row for this container.
            from control_plane.db import make_engine, make_session_factory
            from control_plane.models_db import tasks

            engine = make_engine(app_settings)  # type: ignore[arg-type]
            factory = make_session_factory(engine)
            async with factory() as s:
                count = (
                    await s.execute(
                        select(func.count())
                        .select_from(tasks)
                        .where(tasks.c.container_id == cid)
                    )
                ).scalar_one()
            await engine.dispose()
            assert count == 1, f"expected 1 task row, got {count}"
        finally:
            await c.request(
                "DELETE",
                f"/v1/containers/{cid}",
                headers=headers,
            )

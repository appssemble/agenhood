from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = [pytest.mark.integration]


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_config_snapshot_is_immutable_across_patch(
    seeded_app: object, app_settings: object
) -> None:
    headers = {"Authorization": "Bearer tk_live_seedkey"}
    async with await _client(seeded_app) as c:
        r = await c.post(
            "/v1/containers",
            headers=headers,
            json={
                "name": "snap",
                "config": {
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "system_prompt": "PROMPT_A",
                    "tools": ["read_file", "write_file"],
                },
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        try:
            # Task A is submitted while config has PROMPT_A.
            a = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
                json={"prompt": "a"},
            )
            assert a.status_code == 200, a.text
            tid_a = a.json()["task_id"]

            # PATCH config to PROMPT_B.
            p = await c.patch(
                f"/v1/containers/{cid}/config",
                headers=headers,
                json={
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "system_prompt": "PROMPT_B",
                    "tools": ["read_file", "write_file"],
                },
            )
            assert p.status_code == 200, p.text
            assert p.json()["config"]["system_prompt"] == "PROMPT_B"

            # Task B is submitted after the PATCH — should see PROMPT_B.
            b = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=headers,
                json={"prompt": "b"},
            )
            assert b.status_code == 200, b.text
            tid_b = b.json()["task_id"]

            # Assert snapshots directly in the DB.
            from control_plane.db import make_engine, make_session_factory
            from control_plane.models_db import tasks

            engine = make_engine(app_settings)  # type: ignore[arg-type]
            factory = make_session_factory(engine)
            async with factory() as s:
                snap_a = (
                    await s.execute(
                        select(tasks.c.config_snapshot).where(tasks.c.id == tid_a)
                    )
                ).scalar_one()
                snap_b = (
                    await s.execute(
                        select(tasks.c.config_snapshot).where(tasks.c.id == tid_b)
                    )
                ).scalar_one()
            await engine.dispose()

            # Task A's snapshot must still reflect PROMPT_A.
            assert snap_a["system_prompt"] == "PROMPT_A", (
                f"snap_a system_prompt={snap_a.get('system_prompt')!r}, expected 'PROMPT_A'"
            )
            # Task B's snapshot must reflect PROMPT_B.
            assert snap_b["system_prompt"] == "PROMPT_B", (
                f"snap_b system_prompt={snap_b.get('system_prompt')!r}, expected 'PROMPT_B'"
            )
        finally:
            await c.request(
                "DELETE",
                f"/v1/containers/{cid}",
                headers=headers,
            )

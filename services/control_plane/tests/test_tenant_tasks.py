from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane.routers.tasks import recent_tenant_tasks
from analytics_seed import insert_container, insert_task, insert_tenant


@pytest.mark.asyncio
async def test_recent_tenant_tasks_orders_and_labels(db_session) -> None:
    await insert_tenant(db_session, "tt_ten_a")
    await insert_container(db_session, cid="tt_c1", tenant_id="tt_ten_a", name="support-bot")
    await insert_container(db_session, cid="tt_c2", tenant_id="tt_ten_a", name="qa-runner")
    await insert_task(db_session, tid="tt_old", tenant_id="tt_ten_a", container_id="tt_c1",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC))
    await insert_task(db_session, tid="tt_new", tenant_id="tt_ten_a", container_id="tt_c2",
                      created_at=datetime(2026, 5, 27, 18, tzinfo=UTC))

    out = await recent_tenant_tasks(db_session, tenant_id="tt_ten_a", limit=10)
    assert [t.task_id for t in out] == ["tt_new", "tt_old"]  # newest first
    assert out[0].container_name == "qa-runner"
    assert out[1].container_name == "support-bot"


@pytest.mark.asyncio
async def test_recent_tenant_tasks_respects_limit_and_tenant(db_session) -> None:
    await insert_tenant(db_session, "tt_lim_a")
    await insert_tenant(db_session, "tt_lim_b")
    await insert_container(db_session, cid="tt_lim_c1", tenant_id="tt_lim_a", name="a")
    await insert_container(db_session, cid="tt_lim_c2", tenant_id="tt_lim_b", name="b")
    for i in range(3):
        await insert_task(db_session, tid=f"tt_lim_a{i}", tenant_id="tt_lim_a", container_id="tt_lim_c1",
                          created_at=datetime(2026, 5, 27, 9 + i, tzinfo=UTC))
    await insert_task(db_session, tid="tt_lim_b0", tenant_id="tt_lim_b", container_id="tt_lim_c2",
                      created_at=datetime(2026, 5, 27, 23, tzinfo=UTC))

    out = await recent_tenant_tasks(db_session, tenant_id="tt_lim_a", limit=2)
    assert len(out) == 2
    assert all(t.task_id.startswith("tt_lim_a") for t in out)  # tt_lim_b excluded

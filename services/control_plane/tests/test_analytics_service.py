from __future__ import annotations

from datetime import UTC, datetime

import pytest

from control_plane import analytics_service as svc
from analytics_seed import insert_container, insert_task, insert_tenant


@pytest.mark.asyncio
async def test_usage_series_buckets_by_hour_and_zero_fills(db_session) -> None:
    await insert_tenant(db_session, "ten_hr")
    await insert_container(db_session, cid="hc1", tenant_id="ten_hr", name="bot")
    # Two tasks in the 09:00 hour, none at 10:00, one in the 11:00 hour.
    await insert_task(db_session, tid="h1", tenant_id="ten_hr", container_id="hc1",
                      created_at=datetime(2026, 5, 27, 9, 5, tzinfo=UTC),
                      tokens_in=100, tokens_out=40, iterations=2)
    await insert_task(db_session, tid="h2", tenant_id="ten_hr", container_id="hc1",
                      created_at=datetime(2026, 5, 27, 9, 50, tzinfo=UTC),
                      tokens_in=50, tokens_out=10, iterations=1)
    await insert_task(db_session, tid="h3", tenant_id="ten_hr", container_id="hc1",
                      created_at=datetime(2026, 5, 27, 11, 30, tzinfo=UTC),
                      tokens_in=7, tokens_out=3, iterations=1)

    series = await svc.usage_series(
        db_session, tenant_id="ten_hr",
        start=datetime(2026, 5, 27, 9, tzinfo=UTC),
        end=datetime(2026, 5, 27, 12, tzinfo=UTC), interval="hour",
    )
    assert len(series) == 3  # 09:00, 10:00 (empty), 11:00
    assert series[0].tokens_in == 150 and series[0].tokens_out == 50
    assert series[0].tasks == 2 and series[0].iterations == 3
    assert series[1].tasks == 0 and series[1].tokens_in == 0  # zero-filled hour
    assert series[2].tokens_in == 7 and series[2].tasks == 1


@pytest.mark.asyncio
async def test_usage_series_buckets_by_day_and_zero_fills(db_session) -> None:
    await insert_tenant(db_session, "ten_a")
    await insert_container(db_session, cid="c1", tenant_id="ten_a", name="bot")
    # Two tasks on day 1, none on day 2, one on day 3.
    await insert_task(db_session, tid="t1", tenant_id="ten_a", container_id="c1",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC),
                      tokens_in=100, tokens_out=40, iterations=2)
    await insert_task(db_session, tid="t2", tenant_id="ten_a", container_id="c1",
                      created_at=datetime(2026, 5, 27, 18, tzinfo=UTC),
                      tokens_in=50, tokens_out=10, iterations=1)
    await insert_task(db_session, tid="t3", tenant_id="ten_a", container_id="c1",
                      created_at=datetime(2026, 5, 29, 12, tzinfo=UTC),
                      tokens_in=7, tokens_out=3, iterations=1)

    series = await svc.usage_series(
        db_session, tenant_id="ten_a",
        start=datetime(2026, 5, 27, tzinfo=UTC),
        end=datetime(2026, 5, 30, tzinfo=UTC), interval="day",
    )
    assert len(series) == 3  # 27, 28 (empty), 29
    assert series[0].tokens_in == 150 and series[0].tokens_out == 50
    assert series[0].tasks == 2 and series[0].iterations == 3
    assert series[1].tokens_in == 0 and series[1].tasks == 0  # zero-filled
    assert series[2].tokens_in == 7 and series[2].tasks == 1


@pytest.mark.asyncio
async def test_usage_series_isolates_tenants(db_session) -> None:
    # Use distinct IDs from the first test to avoid PK collisions in the
    # session-scoped DB (insert_tenant commits; rollback-per-test only covers
    # uncommitted changes).
    await insert_tenant(db_session, "iso_ten_a")
    await insert_tenant(db_session, "iso_ten_b")
    await insert_container(db_session, cid="iso_c1", tenant_id="iso_ten_a", name="a")
    await insert_container(db_session, cid="iso_c2", tenant_id="iso_ten_b", name="b")
    await insert_task(db_session, tid="iso_ta", tenant_id="iso_ten_a", container_id="iso_c1",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC), tokens_in=100)
    await insert_task(db_session, tid="iso_tb", tenant_id="iso_ten_b", container_id="iso_c2",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC), tokens_in=999)

    series = await svc.usage_series(
        db_session, tenant_id="iso_ten_a",
        start=datetime(2026, 5, 27, tzinfo=UTC),
        end=datetime(2026, 5, 28, tzinfo=UTC), interval="day",
    )
    assert len(series) == 1
    assert series[0].tokens_in == 100  # iso_ten_b's 999 excluded


@pytest.mark.asyncio
async def test_breakdown_by_container_resolves_name_label(db_session) -> None:
    await insert_tenant(db_session, "bkd_ten_c")
    await insert_container(db_session, cid="bkd_c1", tenant_id="bkd_ten_c", name="support-bot")
    await insert_container(db_session, cid="bkd_c2", tenant_id="bkd_ten_c", name="qa-runner")
    await insert_task(db_session, tid="bkd_t1", tenant_id="bkd_ten_c", container_id="bkd_c1",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC),
                      tokens_in=100, tokens_out=40)
    await insert_task(db_session, tid="bkd_t2", tenant_id="bkd_ten_c", container_id="bkd_c1",
                      created_at=datetime(2026, 5, 27, 10, tzinfo=UTC), tokens_in=50)
    await insert_task(db_session, tid="bkd_t3", tenant_id="bkd_ten_c", container_id="bkd_c2",
                      created_at=datetime(2026, 5, 27, 11, tzinfo=UTC), tokens_in=10)

    groups = await svc.breakdown(
        db_session, tenant_id="bkd_ten_c",
        start=datetime(2026, 5, 27, tzinfo=UTC),
        end=datetime(2026, 5, 28, tzinfo=UTC), by="container",
    )
    by_key = {g.key: g for g in groups}
    assert by_key["bkd_c1"].label == "support-bot"
    assert by_key["bkd_c1"].tokens_in == 150 and by_key["bkd_c1"].tasks == 2
    assert by_key["bkd_c2"].label == "qa-runner" and by_key["bkd_c2"].tokens_in == 10


@pytest.mark.asyncio
async def test_breakdown_by_status_uses_key_as_label(db_session) -> None:
    await insert_tenant(db_session, "bkd_ten_d")
    await insert_container(db_session, cid="bkd_c3", tenant_id="bkd_ten_d", name="bot")
    await insert_task(db_session, tid="bkd_ts1", tenant_id="bkd_ten_d", container_id="bkd_c3",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC), status="completed")
    await insert_task(db_session, tid="bkd_ts2", tenant_id="bkd_ten_d", container_id="bkd_c3",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC), status="failed")
    await insert_task(db_session, tid="bkd_ts3", tenant_id="bkd_ten_d", container_id="bkd_c3",
                      created_at=datetime(2026, 5, 27, 9, tzinfo=UTC), status="completed")

    groups = await svc.breakdown(
        db_session, tenant_id="bkd_ten_d",
        start=datetime(2026, 5, 27, tzinfo=UTC),
        end=datetime(2026, 5, 28, tzinfo=UTC), by="status",
    )
    by_key = {g.key: g for g in groups}
    assert by_key["completed"].tasks == 2 and by_key["completed"].label == "completed"
    assert by_key["failed"].tasks == 1

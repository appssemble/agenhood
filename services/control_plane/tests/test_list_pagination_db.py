"""Postgres-backed tests for the keyset page queries behind the task, session
and event listings. Ids are prefixed per test because the database is shared.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa

from control_plane.models_db import containers, events, tasks, tenants
from control_plane.pagination import decode_cursor
from control_plane.routers.tasks import (
    container_sessions_page,
    container_tasks_page,
    task_events_page,
)

pytestmark = pytest.mark.integration

_CFG = {"driver": "vanilla", "model": "m", "tools": []}
_T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


async def _container(db: Any, prefix: str) -> tuple[str, str]:
    tid, cid = f"{prefix}_ten", f"{prefix}_ctr"
    await db.execute(sa.insert(tenants).values(
        id=tid, name=tid, limits={}, status="active", created_at=_T0,
    ))
    await db.execute(sa.insert(containers).values(
        id=cid, tenant_id=tid, name=cid, docker_name=f"dn-{cid}",
        volume_name=f"vol-{cid}", shim_token="tok", image_tag="t",
        config=_CFG, status="running", created_at=_T0, status_changed_at=_T0,
    ))
    return tid, cid


async def _task(
    db: Any, *, tid: str, cid: str, task_id: str, created_at: datetime,
    session_id: str | None = None, status: str = "succeeded",
) -> None:
    await db.execute(sa.insert(tasks).values(
        id=task_id, tenant_id=tid, container_id=cid, driver="vanilla", model="m",
        body={"prompt": "p"}, config_snapshot=_CFG, status=status,
        tokens_in=0, tokens_out=0, iterations_used=0,
        created_at=created_at, session_id=session_id,
    ))


async def _all_task_pages(db: Any, *, limit: int, **filters: Any) -> list[list[str]]:
    pages: list[list[str]] = []
    after = None
    while True:
        rows, cursor = await container_tasks_page(
            db, limit=limit, after=after,
            scheduled_task_id=filters.get("scheduled_task_id"),
            session_id=filters.get("session_id"),
            tenant_id=filters["tenant_id"], cid=filters["cid"],
        )
        pages.append([r.id for r in rows])
        if cursor is None:
            return pages
        after = decode_cursor(cursor)


@pytest.mark.asyncio
async def test_task_pages_cover_everything_once_including_ties(db_session) -> None:
    tid, cid = await _container(db_session, "pgt1")
    # Three tasks share one timestamp so the id tie-break decides their order.
    stamps = [_T0, _T0, _T0, _T0 + timedelta(seconds=1), _T0 + timedelta(seconds=2)]
    for i, ts in enumerate(stamps):
        await _task(db_session, tid=tid, cid=cid, task_id=f"pgt1_{i}", created_at=ts)

    pages = await _all_task_pages(db_session, limit=2, tenant_id=tid, cid=cid)

    assert pages == [["pgt1_4", "pgt1_3"], ["pgt1_2", "pgt1_1"], ["pgt1_0"]]


@pytest.mark.asyncio
async def test_task_page_exactly_full_has_no_next_cursor(db_session) -> None:
    tid, cid = await _container(db_session, "pgt2")
    for i in range(3):
        await _task(db_session, tid=tid, cid=cid, task_id=f"pgt2_{i}",
                    created_at=_T0 + timedelta(seconds=i))

    rows, cursor = await container_tasks_page(
        db_session, tenant_id=tid, cid=cid, scheduled_task_id=None,
        session_id=None, limit=3, after=None,
    )

    assert len(rows) == 3
    assert cursor is None


@pytest.mark.asyncio
async def test_task_pages_respect_session_filter(db_session) -> None:
    tid, cid = await _container(db_session, "pgt3")
    for i in range(5):
        await _task(db_session, tid=tid, cid=cid, task_id=f"pgt3_{i}",
                    created_at=_T0 + timedelta(seconds=i),
                    session_id="s_a" if i % 2 == 0 else "s_b")

    pages = await _all_task_pages(
        db_session, limit=1, tenant_id=tid, cid=cid, session_id="s_a",
    )

    assert pages == [["pgt3_4"], ["pgt3_2"], ["pgt3_0"]]


@pytest.mark.asyncio
async def test_task_pages_are_tenant_scoped(db_session) -> None:
    tid, cid = await _container(db_session, "pgt4")
    await _task(db_session, tid=tid, cid=cid, task_id="pgt4_0", created_at=_T0)

    rows, _ = await container_tasks_page(
        db_session, tenant_id="someone_else", cid=cid, scheduled_task_id=None,
        session_id=None, limit=10, after=None,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_session_pages_cover_everything_once_including_ties(db_session) -> None:
    tid, cid = await _container(db_session, "pgs1")
    # s_x and s_y end at the same moment; s_z is the most recent.
    await _task(db_session, tid=tid, cid=cid, task_id="pgs1_0", created_at=_T0, session_id="s_x")
    await _task(db_session, tid=tid, cid=cid, task_id="pgs1_1", created_at=_T0, session_id="s_y")
    await _task(db_session, tid=tid, cid=cid, task_id="pgs1_2",
                created_at=_T0 - timedelta(hours=1), session_id="s_y")
    await _task(db_session, tid=tid, cid=cid, task_id="pgs1_3",
                created_at=_T0 + timedelta(seconds=5), session_id="s_z", status="running")
    await _task(db_session, tid=tid, cid=cid, task_id="pgs1_4", created_at=_T0)  # no session

    everything, none_cursor = await container_sessions_page(
        db_session, tenant_id=tid, cid=cid, limit=None, after=None,
    )
    pages: list[list[str]] = []
    after = None
    while True:
        rows, cursor = await container_sessions_page(
            db_session, tenant_id=tid, cid=cid, limit=1, after=after,
        )
        pages.append([r.session_id for r in rows])
        if cursor is None:
            break
        after = decode_cursor(cursor)

    assert none_cursor is None
    assert [r.session_id for r in everything] == ["s_z", "s_y", "s_x"]
    assert pages == [["s_z"], ["s_y"], ["s_x"]]
    s_y = everything[1]
    assert s_y.task_count == 2
    assert everything[0].busy is True


@pytest.mark.asyncio
async def test_event_pages_follow_after_seq(db_session) -> None:
    tid, cid = await _container(db_session, "pge1")
    await _task(db_session, tid=tid, cid=cid, task_id="pge1_t", created_at=_T0)
    for seq in range(1, 6):
        await db_session.execute(sa.insert(events).values(
            task_id="pge1_t", seq=seq, type="log", payload={"n": seq}, ts=_T0,
        ))

    everything, none_next = await task_events_page(
        db_session, task_id="pge1_t", after_seq=None, limit=None,
    )
    tail, tail_next = await task_events_page(
        db_session, task_id="pge1_t", after_seq=3, limit=None,
    )
    first, next_seq = await task_events_page(
        db_session, task_id="pge1_t", after_seq=None, limit=2,
    )
    second, next_seq2 = await task_events_page(
        db_session, task_id="pge1_t", after_seq=next_seq, limit=2,
    )
    last, next_seq3 = await task_events_page(
        db_session, task_id="pge1_t", after_seq=next_seq2, limit=2,
    )

    assert [e.seq for e in everything] == [1, 2, 3, 4, 5] and none_next is None
    assert [e.seq for e in tail] == [4, 5] and tail_next is None
    assert [e.seq for e in first] == [1, 2] and next_seq == 2
    assert [e.seq for e in second] == [3, 4] and next_seq2 == 4
    assert [e.seq for e in last] == [5] and next_seq3 is None

"""Postgres-backed tests for the idle-pause candidate query (spec §4.8).

Exercises the real SQL semantics: per-tenant ``idle_pause_minutes`` threshold,
GREATEST-based idle accounting (NULL last_task_at, just-resumed containers), and
exclusion of busy / non-running containers.

Requires a docker daemon (testcontainers Postgres) — marked ``integration`` so it
runs in the CI integration job. Container/tenant ids are uniquely prefixed per
test because the session-scoped database is shared and inserts are committed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from control_plane import idle
from control_plane.models_db import containers, tenants

pytestmark = pytest.mark.integration

_CFG = {
    "driver": "vanilla", "model": "m", "system_prompt": "",
    "system_prompt_mode": "augment", "tools": [],
    "context": {"variables": {}, "text": None, "files": []},
}


async def _tenant(db, tid: str, idle_minutes: int | None) -> None:
    limits = {} if idle_minutes is None else {"idle_pause_minutes": idle_minutes}
    await db.execute(sa.insert(tenants).values(
        id=tid, name=tid, limits=limits, status="active", created_at=datetime.now(UTC),
    ))
    await db.commit()


async def _container(
    db, *, cid: str, tid: str, status: str = "running",
    created_min_ago: float, status_changed_min_ago: float,
    last_task_min_ago: float | None,
) -> None:
    now = datetime.now(UTC)
    last_task_at = None if last_task_min_ago is None else now - timedelta(minutes=last_task_min_ago)
    await db.execute(sa.insert(containers).values(
        id=cid, tenant_id=tid, name=cid,
        docker_name=f"dn-{cid}", volume_name=f"vol-{cid}", shim_token="tok",
        image_tag="t", config=_CFG, status=status,
        created_at=now - timedelta(minutes=created_min_ago),
        status_changed_at=now - timedelta(minutes=status_changed_min_ago),
        last_task_at=last_task_at,
    ))
    await db.commit()


async def _task(db, *, tid_row: str, tenant_id: str, container_id: str, status: str) -> None:
    from control_plane.models_db import tasks
    await db.execute(sa.insert(tasks).values(
        id=tid_row, tenant_id=tenant_id, container_id=container_id,
        driver="vanilla", model="m", body={"prompt": "p"}, config_snapshot=_CFG,
        status=status, tokens_in=0, tokens_out=0, iterations_used=0,
        created_at=datetime.now(UTC),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_idle_candidates_selects_idle_running_only(db_session) -> None:
    await _tenant(db_session, "ipA", idle_minutes=20)

    # Idle for 30 min, no tasks -> candidate.
    await _container(db_session, cid="ipA_idle", tid="ipA",
                     created_min_ago=60, status_changed_min_ago=30, last_task_min_ago=30)
    # Ran a task 5 min ago -> below threshold, not idle.
    await _container(db_session, cid="ipA_recent", tid="ipA",
                     created_min_ago=60, status_changed_min_ago=30, last_task_min_ago=5)
    # Paused -> not running, never a candidate even if long idle.
    await _container(db_session, cid="ipA_paused", tid="ipA", status="paused",
                     created_min_ago=120, status_changed_min_ago=90, last_task_min_ago=90)
    # Never ran a task (NULL last_task_at) but provisioned 30 min ago -> candidate
    # via the created_at floor (GREATEST skips NULL).
    await _container(db_session, cid="ipA_neverrun", tid="ipA",
                     created_min_ago=30, status_changed_min_ago=30, last_task_min_ago=None)

    cands = set(await idle._idle_candidates(db_session))

    assert "ipA_idle" in cands
    assert "ipA_neverrun" in cands
    assert "ipA_recent" not in cands
    assert "ipA_paused" not in cands


@pytest.mark.asyncio
async def test_idle_candidates_excludes_busy_container(db_session) -> None:
    await _tenant(db_session, "ipB", idle_minutes=20)
    # Long idle by last_task_at, but has an in-flight task -> excluded.
    await _container(db_session, cid="ipB_busy", tid="ipB",
                     created_min_ago=120, status_changed_min_ago=60, last_task_min_ago=60)
    await _task(db_session, tid_row="ipB_t", tenant_id="ipB",
                container_id="ipB_busy", status="running")

    cands = set(await idle._idle_candidates(db_session))
    assert "ipB_busy" not in cands


@pytest.mark.asyncio
async def test_idle_candidates_excludes_just_resumed_container(db_session) -> None:
    # Regression for the wake race: a container resumed on a new task has a stale
    # last_task_at (from before it was paused) but a fresh status_changed_at. It
    # must NOT be picked, or the sweep would re-pause a container being woken
    # before the task row is even written.
    await _tenant(db_session, "ipC", idle_minutes=20)
    await _container(db_session, cid="ipC_woken", tid="ipC",
                     created_min_ago=120, status_changed_min_ago=0, last_task_min_ago=90)

    cands = set(await idle._idle_candidates(db_session))
    assert "ipC_woken" not in cands


@pytest.mark.asyncio
async def test_idle_candidates_uses_per_tenant_threshold(db_session) -> None:
    await _tenant(db_session, "ipShort", idle_minutes=5)     # short fuse
    await _tenant(db_session, "ipDefault", idle_minutes=None)  # no limit -> default 20

    # Idle 10 min: over the 5-min tenant's threshold, under the default 20.
    await _container(db_session, cid="ipShort_c", tid="ipShort",
                     created_min_ago=60, status_changed_min_ago=10, last_task_min_ago=10)
    await _container(db_session, cid="ipDefault_under", tid="ipDefault",
                     created_min_ago=60, status_changed_min_ago=10, last_task_min_ago=10)
    # Idle 25 min on the default tenant: over the default 20.
    await _container(db_session, cid="ipDefault_over", tid="ipDefault",
                     created_min_ago=60, status_changed_min_ago=25, last_task_min_ago=25)

    cands = set(await idle._idle_candidates(db_session))
    assert "ipShort_c" in cands           # 10 > 5
    assert "ipDefault_under" not in cands  # 10 < 20 (default)
    assert "ipDefault_over" in cands       # 25 > 20 (default)

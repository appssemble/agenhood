"""Incident A regression: lifecycle.pause releases the container-row lock BEFORE docker stop.

The idle-pause sweep once held the container-row write lock (running→pausing
UPDATE uncommitted) across the full docker stop grace period (~15 s). Concurrent
writers blocked on the row and DB-pool connections were exhausted, causing
control-plane routes to time out until the sweep committed.

Fix (lifecycle.py:286): ``await db.commit()`` is called immediately after the
running→pausing CAS, collapsing the lock window from ~15 s to ms. The docker
stop happens in the NEXT implicit transaction, so no row lock is held.

This test locks that ordering via a real Postgres row-lock probe:

    1. Monkeypatch ``lifecycle.docker_ctl.stop`` with a probe coroutine.
    2. During the (mocked) stop, a SECOND independent session executes
       ``SELECT status ... FOR UPDATE NOWAIT`` on the container row.
    3. Assert:
       - ``status == 'pausing'``  →  the running→pausing CAS was already committed
       - NOWAIT succeeds          →  the write lock was already released
    4. Assert final status == 'paused' (pause completed correctly).

Revert-fail proof (bite-check): if ``await db.commit()`` is moved to AFTER
``docker_ctl.stop`` (reverting the fix), the pause session still holds the
uncommitted write lock when the probe fires → NOWAIT raises SQLSTATE 55P03 →
``observed['locked_ok']`` becomes False → assertion fails.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from control_plane import lifecycle
from control_plane.models_db import containers, tenants

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

_CFG = {
    "driver": "vanilla",
    "model": "m",
    "system_prompt": "",
    "system_prompt_mode": "augment",
    "tools": [],
    "context": {"variables": {}, "text": None, "files": []},
}


class _FakeShim:
    """Minimal shim stub: /shutdown is a no-op, cancel_all is a no-op."""

    async def post(self, *a: object, **k: object) -> None:
        return None

    async def cancel_all(self, *a: object, **k: object) -> None:
        return None


def _is_lock_unavailable(exc: BaseException) -> bool:
    """True if *exc* wraps a Postgres lock_not_available (SQLSTATE 55P03).

    asyncpg raises LockNotAvailableError; SQLAlchemy wraps it in DBAPIError
    with the original asyncpg exception on .orig, which carries .sqlstate.
    Mirrors the _is_deadlock helper in idle.py.
    """
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03"


async def test_pause_commits_pausing_and_releases_lock_before_docker_stop(
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incident A regression: pause() commits running→pausing BEFORE docker stop.

    The container-row write lock must be released before docker_ctl.stop runs.
    A second independent DB session probes the row during the (mocked) stop:

    - ``status == 'pausing'`` proves running→pausing was committed before the stop.
    - ``SELECT ... FOR UPDATE NOWAIT`` success proves the write lock was released.

    If the fix is reverted (commit moved to after the stop), the probe's NOWAIT
    fails with SQLSTATE 55P03 and/or sees ``status == 'running'`` → test fails.
    """
    engine = create_async_engine(migrated_db, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed a tenant row (FK constraint on containers.tenant_id).
    async with factory() as s:
        await s.execute(
            sa.insert(tenants).values(
                id="ten_lock_incA",
                name="ten_lock_incA",
                limits={},
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()

    cid = "con_lock_incA_reg"

    # Seed a committed running container so the second session can see it.
    async with factory() as s:
        await s.execute(
            sa.insert(containers).values(
                id=cid,
                tenant_id="ten_lock_incA",
                name=cid,
                docker_name=f"dn-{cid}",
                volume_name=f"vol-{cid}",
                shim_token="tok",
                image_tag="t",
                config=_CFG,
                status="running",
                created_at=datetime.now(UTC),
                status_changed_at=datetime.now(UTC),
            )
        )
        await s.commit()

    observed: dict[str, object] = {}

    async def probe_stop(docker_client: object, name: str, grace: int) -> None:
        """Probe injected at the moment of docker_ctl.stop inside lifecycle.pause.

        Runs in a SEPARATE DB session (independent connection) to verify that:
        - The running→pausing UPDATE was committed (status == 'pausing')
        - The row write lock was released (FOR UPDATE NOWAIT succeeds)

        If the commit is held until AFTER the stop (reverted fix), the pause
        session's uncommitted write lock blocks this NOWAIT → 55P03 → test fails.
        """
        async with factory() as probe:
            try:
                row = (
                    await probe.execute(
                        sa.text(
                            "SELECT status FROM containers "
                            "WHERE id = :c FOR UPDATE NOWAIT"
                        ),
                        {"c": cid},
                    )
                ).first()
                observed["status"] = row[0] if row else None
                observed["locked_ok"] = True
            except Exception as exc:  # noqa: BLE001
                # NOWAIT blocked → lock was still held → regression
                observed["locked_ok"] = not _is_lock_unavailable(exc)
                observed["error"] = repr(exc)
            # Release before lifecycle.pause's pausing→paused UPDATE
            await probe.rollback()

    monkeypatch.setattr(lifecycle.docker_ctl, "stop", probe_stop)

    async with factory() as pause_session:
        await lifecycle.pause(pause_session, object(), _FakeShim(), cid)

    # -- core regression assertions ------------------------------------------
    # status must already read 'pausing' during the stop (commit-before-stop)
    assert observed.get("status") == "pausing", (
        f"Expected status='pausing' in probe — commit must happen BEFORE docker stop. "
        f"Got: {observed}"
    )
    # the row must be lockable — write lock must be released before docker stop
    assert observed.get("locked_ok") is True, (
        f"Expected FOR UPDATE NOWAIT to succeed — row lock must be released before docker stop. "
        f"Got: {observed}"
    )

    # pause() must have completed the full running→pausing→paused transition
    async with factory() as s:
        final = (
            await s.execute(
                sa.select(containers.c.status).where(containers.c.id == cid)
            )
        ).scalar_one()
    assert final == "paused", f"Expected final status='paused'; got {final!r}"

    await engine.dispose()

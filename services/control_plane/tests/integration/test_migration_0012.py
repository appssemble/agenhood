"""Integration test: migration 0012 — unique data-migration assertions only.

Column/index/table existence is now covered by the upgrade-clean gate and the
drift equality guard (index swap is locked by test_migration_0014.py).
What remains here is the data-migration backfill behaviour: a membership can be
inserted for a newly-added user (schema write-readiness) and, crucially, the
backfill creates a membership for a user that existed BEFORE the migration ran.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]


@pytest.mark.asyncio
async def test_memberships_write_readiness(migrated_db: str) -> None:
    """Verify the memberships table accepts inserts at head (schema write-check)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO tenants (id, name, limits, status) "
                "VALUES ('ten_mig', 'Mig', '{}'::jsonb, 'active')"))
            await conn.execute(text(
                "INSERT INTO users (id, email, name, password_hash, is_staff) "
                "VALUES ('usr_mig', 'mig@x.io', 'Mig', 'h', false)"))
            await conn.execute(text(
                "INSERT INTO memberships (id, user_id, tenant_id, role, status) "
                "VALUES ('mbr_mig', 'usr_mig', 'ten_mig', 'admin', 'active')"))
            n = (await conn.execute(text(
                "SELECT count(*) FROM memberships WHERE user_id='usr_mig'"))).scalar_one()
            assert n == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_creates_membership_for_preexisting_user(migrated_db: str) -> None:
    """The 0012 backfill must create a membership for a user that existed BEFORE
    the migration ran. migrated_db is empty at migration time, so we roll back to
    0011, seed a non-staff user, then re-upgrade and assert the backfill fired."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    this_dir = os.path.dirname(os.path.abspath(__file__))   # tests/integration
    cp_dir = os.path.dirname(os.path.dirname(this_dir))     # services/control_plane
    # alembic from the env running pytest (mirrors conftest._VENV_ALEMBIC); the
    # old hardcoded repo-root/.venv path existed in neither CI nor local.
    alembic_bin = os.path.join(os.path.dirname(sys.executable), "alembic")
    if not os.path.exists(alembic_bin):
        alembic_bin = shutil.which("alembic") or alembic_bin
    ini = os.path.join(cp_dir, "alembic.ini")
    env = {**os.environ, "DATABASE_URL": migrated_db, "PYTHONPATH": cp_dir}

    def _alembic(*args: str) -> None:
        subprocess.run([alembic_bin, "-c", ini, *args], check=True, env=env, cwd=cp_dir)

    engine = create_async_engine(migrated_db)
    _alembic("downgrade", "0011_scheduled_tasks")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO tenants (id, name, limits, status) "
                "VALUES ('ten_bf', 'BF', '{}'::jsonb, 'active') ON CONFLICT (id) DO NOTHING"))
            await conn.execute(text(
                "INSERT INTO users (id, tenant_id, email, name, password_hash, role, is_staff) "
                "VALUES ('usr_bf', 'ten_bf', 'bf@x.io', 'BF', 'h', 'admin', false) "
                "ON CONFLICT (id) DO NOTHING"))
        _alembic("upgrade", "head")
        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT tenant_id, role FROM memberships WHERE user_id='usr_bf'"))).first()
            assert row is not None, "backfill did not create a membership for the pre-existing user"
            assert row[0] == "ten_bf"
            assert row[1] == "admin"
            # leave the shared session DB clean
            await conn.execute(text("DELETE FROM memberships WHERE user_id='usr_bf'"))
            await conn.execute(text("DELETE FROM users WHERE id='usr_bf'"))
            await conn.execute(text("DELETE FROM tenants WHERE id='ten_bf'"))
    finally:
        _alembic("upgrade", "head")   # restore shared DB to head even if assertions failed
        await engine.dispose()

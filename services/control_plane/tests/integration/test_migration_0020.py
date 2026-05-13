"""Integration test: migration 0020 reworks scheduled_tasks to be tenant-scoped
with a polymorphic ``target`` JSONB, and backfills inline ``task_body`` rows into
auto-created ``prompts``. Mirrors tests/integration/test_migration_0012.py's
alembic downgrade/seed/upgrade cycle.
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
async def test_scheduled_tasks_target_backfill(migrated_db: str) -> None:
    """Downgrade to 0019, seed an OLD-shape scheduled_tasks row with an inline
    task_body, upgrade to head, and assert the backfill created a prompt and a
    polymorphic target, dropped the old columns, and renamed last_task_id."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    this_dir = os.path.dirname(os.path.abspath(__file__))   # tests/integration
    cp_dir = os.path.dirname(os.path.dirname(this_dir))     # services/control_plane
    alembic_bin = os.path.join(os.path.dirname(sys.executable), "alembic")
    if not os.path.exists(alembic_bin):
        alembic_bin = shutil.which("alembic") or alembic_bin
    ini = os.path.join(cp_dir, "alembic.ini")
    env = {**os.environ, "DATABASE_URL": migrated_db, "PYTHONPATH": cp_dir}

    def _alembic(*args: str) -> None:
        subprocess.run([alembic_bin, "-c", ini, *args], check=True, env=env, cwd=cp_dir)

    engine = create_async_engine(migrated_db)
    _alembic("downgrade", "0019_workflows")
    try:
        # Seed at the OLD (0019-era) schema: tenant + container + an inline schedule.
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO tenants (id, name, limits, status) "
                "VALUES ('ten_m20', 'M20', '{}'::jsonb, 'active') "
                "ON CONFLICT (id) DO NOTHING"))
            await conn.execute(text(
                "INSERT INTO containers "
                "(id, tenant_id, name, docker_name, volume_name, shim_token, "
                " image_tag, config, status) "
                "VALUES ('cnt_m20', 'ten_m20', 'C20', 'dock_m20', 'vol_m20', 'tok', "
                "'test', '{}'::jsonb, 'running') "
                "ON CONFLICT (id) DO NOTHING"))
            await conn.execute(text(
                "INSERT INTO scheduled_tasks "
                "(id, tenant_id, container_id, name, driver, model, task_body, "
                " schedule, timezone, enabled, last_task_id) "
                "VALUES ('sch_m20', 'ten_m20', 'cnt_m20', 'Nightly', 'claude-code', "
                "NULL, '{\"prompt\":\"do x\"}'::jsonb, "
                "'{\"kind\":\"cron\",\"expr\":\"0 0 * * *\"}'::jsonb, 'UTC', true, "
                "'tsk_old')"))

        _alembic("upgrade", "head")

        async with engine.begin() as conn:
            # (a) a backfilled prompt exists for the tenant with body 'do x'.
            prow = (await conn.execute(text(
                "SELECT id, name, body FROM prompts WHERE tenant_id='ten_m20'"))).first()
            assert prow is not None, "backfill did not create a prompt"
            pid, pname, pbody = prow
            assert pbody == "do x"
            assert pid.startswith("prm_")
            assert pname.startswith("(migrated) ")

            # (b) the schedule's target is the polymorphic prompt reference.
            target = (await conn.execute(text(
                "SELECT target FROM scheduled_tasks WHERE id='sch_m20'"))).scalar_one()
            assert target == {
                "kind": "prompt",
                "container_id": "cnt_m20",
                "prompt_id": pid,
                "variables": {},
            }

            # (c) old columns are gone.
            cols = {
                r[0] for r in await conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='scheduled_tasks'"))
            }
            assert "task_body" not in cols
            assert "container_id" not in cols
            assert "driver" not in cols
            assert "model" not in cols

            # (d) last_task_id renamed to last_run_ref.
            assert "last_run_ref" in cols
            assert "last_task_id" not in cols
            lrr = (await conn.execute(text(
                "SELECT last_run_ref FROM scheduled_tasks WHERE id='sch_m20'"))).scalar_one()
            assert lrr == "tsk_old"

            # Clean up seeded rows on the shared session DB.
            await conn.execute(text("DELETE FROM scheduled_tasks WHERE id='sch_m20'"))
            await conn.execute(text("DELETE FROM prompts WHERE tenant_id='ten_m20'"))
            await conn.execute(text("DELETE FROM containers WHERE id='cnt_m20'"))
            await conn.execute(text("DELETE FROM tenants WHERE id='ten_m20'"))
    finally:
        _alembic("upgrade", "head")   # restore shared DB to head even on failure
        await engine.dispose()

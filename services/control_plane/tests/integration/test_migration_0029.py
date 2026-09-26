"""Integration test: 0029 gives empty codex tool lists web_search, and its
downgrade restores the empty lists old code expects."""
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
async def test_codex_default_tools_backfill(migrated_db: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    this_dir = os.path.dirname(os.path.abspath(__file__))
    cp_dir = os.path.dirname(os.path.dirname(this_dir))
    alembic_bin = os.path.join(os.path.dirname(sys.executable), "alembic")
    if not os.path.exists(alembic_bin):
        alembic_bin = shutil.which("alembic") or alembic_bin
    ini = os.path.join(cp_dir, "alembic.ini")
    env = {**os.environ, "DATABASE_URL": migrated_db, "PYTHONPATH": cp_dir}

    def _alembic(*args: str) -> None:
        subprocess.run([alembic_bin, "-c", ini, *args], check=True, env=env, cwd=cp_dir)

    async def _tools(conn, sql: str):
        return (await conn.execute(text(sql))).scalar_one()

    engine = create_async_engine(migrated_db)
    _alembic("downgrade", "0028_env_vars")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO tenants (id, name, limits, status) "
                "VALUES ('ten_m29', 'M29', '{}'::jsonb, 'active') ON CONFLICT (id) DO NOTHING"))
            await conn.execute(text(
                "INSERT INTO templates (id, tenant_id, name, driver, tools) VALUES "
                "('tpl_m29_codex', 'ten_m29', 'c', 'codex', '[]'::jsonb), "
                "('tpl_m29_vanilla', 'ten_m29', 'v', 'vanilla', '[]'::jsonb)"))
            await conn.execute(text(
                "INSERT INTO containers "
                "(id, tenant_id, name, docker_name, volume_name, shim_token, image_tag, "
                " config, status) VALUES "
                "('cnt_m29_empty', 'ten_m29', 'a', 'd1', 'v1', 't', 'test', "
                " '{\"driver\":\"codex\",\"model\":\"m\",\"tools\":[]}'::jsonb, 'running'), "
                "('cnt_m29_missing', 'ten_m29', 'b', 'd2', 'v2', 't', 'test', "
                " '{\"driver\":\"codex\",\"model\":\"m\"}'::jsonb, 'running'), "
                "('cnt_m29_vanilla', 'ten_m29', 'c', 'd3', 'v3', 't', 'test', "
                " '{\"driver\":\"vanilla\",\"model\":\"m\",\"tools\":[]}'::jsonb, 'running')"))

        _alembic("upgrade", "head")

        async with engine.begin() as conn:
            assert await _tools(
                conn, "SELECT tools FROM templates WHERE id='tpl_m29_codex'"
            ) == ["web_search"]
            assert await _tools(
                conn, "SELECT tools FROM templates WHERE id='tpl_m29_vanilla'"
            ) == []
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_empty'"
            ) == ["web_search"]
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_missing'"
            ) == ["web_search"]
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_vanilla'"
            ) == []
            # A user choice made after the upgrade must survive a re-run of the backfill.
            await conn.execute(text(
                "UPDATE containers SET config = jsonb_set(config, '{tools}', '[\"goals\"]'::jsonb) "
                "WHERE id='cnt_m29_empty'"))

        # Re-run just the backfill (stamp moves the version pointer without
        # running the downgrade SQL, so the user's choice is still in place
        # when the upgrade re-runs 0029's UPDATEs).
        _alembic("stamp", "0028_env_vars")
        _alembic("upgrade", "head")

        async with engine.begin() as conn:
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_empty'"
            ) == ["goals"]
            assert await _tools(
                conn, "SELECT tools FROM templates WHERE id='tpl_m29_codex'"
            ) == ["web_search"]

        _alembic("downgrade", "0028_env_vars")

        async with engine.begin() as conn:
            assert await _tools(
                conn, "SELECT tools FROM templates WHERE id='tpl_m29_codex'"
            ) == []
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_empty'"
            ) == []
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_missing'"
            ) == []
            assert await _tools(
                conn, "SELECT config->'tools' FROM containers WHERE id='cnt_m29_vanilla'"
            ) == []
    finally:
        _alembic("upgrade", "head")
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM containers WHERE tenant_id='ten_m29'"))
            await conn.execute(text("DELETE FROM templates WHERE tenant_id='ten_m29'"))
            await conn.execute(text("DELETE FROM tenants WHERE id='ten_m29'"))
        await engine.dispose()

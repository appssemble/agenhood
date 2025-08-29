from __future__ import annotations

import os

import pytest


@pytest.mark.unit
def test_single_head() -> None:
    from tests.integration.migrations._helpers import alembic_script

    heads = alembic_script().get_heads()
    assert len(heads) == 1, f"expected exactly one alembic head, got {heads}"


@pytest.mark.unit
def test_chain_is_linear_and_every_revision_has_callables() -> None:
    from tests.integration.migrations._helpers import alembic_script

    script = alembic_script()
    revs = list(script.walk_revisions())  # newest → oldest
    assert len(revs) >= 21, f"expected ≥21 revisions, walked {len(revs)}"
    for rev in revs:
        # linear chain: 0 (base) or 1 parent per revision
        parents = rev.down_revision
        assert parents is None or isinstance(parents, str), (
            f"{rev.revision} has a branched/merged down_revision: {parents!r}"
        )
        assert callable(getattr(rev.module, "upgrade", None)), f"{rev.revision} lacks upgrade()"
        assert callable(getattr(rev.module, "downgrade", None)), f"{rev.revision} lacks downgrade()"


_DOCKER = pytest.mark.skipif(
    not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
    reason="needs docker for testcontainers postgres",
)


@pytest.mark.integration
@_DOCKER
class TestUpgradeAndDowngrade:
    @pytest.mark.asyncio
    async def test_upgrade_head_from_empty_reaches_single_head(self, migrated_db: str) -> None:
        """`migrated_db` ran `alembic upgrade head` from an empty DB. Prove we
        landed exactly on the single head — i.e. every revision in the walked
        chain applied cleanly. A NEW revision is covered automatically."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from tests.integration.migrations._helpers import head_revision

        engine = create_async_engine(migrated_db)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(text("SELECT version_num FROM alembic_version"))
                applied = row.scalar_one()
        finally:
            await engine.dispose()
        assert applied == head_revision()

    @pytest.mark.asyncio
    async def test_every_model_table_exists_at_head(self, migrated_db: str) -> None:
        """Every model table is present after upgrade head (table-level smoke
        that subsumes the existence half of the folded per-revision tests)."""
        from tests.integration.migrations._helpers import model_schema, reflect_db_schema

        db = await reflect_db_schema(migrated_db)
        missing = set(model_schema()) - set(db)
        assert not missing, f"model tables absent from migrated head: {sorted(missing)}"

    @pytest.mark.asyncio
    async def test_downgrade_base_then_upgrade_head_round_trips(self, migrated_db: str) -> None:
        """Spot-check downgrades: tear the schema down to base and rebuild it.
        Runs alembic via subprocess (mirrors conftest._run_alembic). ALWAYS
        restores the shared session DB to head in finally."""
        import asyncio
        import subprocess
        import sys
        from pathlib import Path

        cp_dir = Path(__file__).resolve().parents[3]
        alembic_bin = str(Path(sys.executable).parent / "alembic")
        env = {**os.environ, "DATABASE_URL": migrated_db, "PYTHONPATH": str(cp_dir)}

        def _alembic(*args: str) -> None:
            subprocess.run([alembic_bin, "-c", str(cp_dir / "alembic.ini"), *args],
                           check=True, env=env, cwd=str(cp_dir))

        try:
            await asyncio.to_thread(_alembic, "downgrade", "base")
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(migrated_db)
            try:
                async with engine.connect() as conn:
                    # alembic_version is empty at base; user tables are gone.
                    n = await conn.execute(text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name='containers'"
                    ))
                    assert n.scalar_one() == 0, "downgrade base left the containers table"
            finally:
                await engine.dispose()
        finally:
            await asyncio.to_thread(_alembic, "upgrade", "head")  # restore shared DB

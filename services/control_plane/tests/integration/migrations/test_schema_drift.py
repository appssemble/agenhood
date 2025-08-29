from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")),
        reason="needs docker for testcontainers postgres",
    ),
]

# Reviewed, intentional asymmetries between models_db.py/tables.py and the
# migrated head. Each entry MUST cite why.
#
# (table, column) present in the MIGRATED head but absent from the MODELS:
MIGRATED_ONLY_ALLOW: set[tuple[str, str]] = {
    # KNOWN DRIFT — memory "control-plane-schema-drift" / audit 2026-06-19:
    # migration 0004 added these three lifecycle-timing columns to the
    # `containers` table, but models_db.containers never declared them.
    # Production always uses `alembic upgrade head` so prod and any
    # alembic-migrated test DB have the columns; `metadata.create_all`-based
    # in-memory test DBs do not, which is the root cause of the drift.
    # Remove these entries once models_db.py (and tables.py if applicable)
    # are corrected to declare last_active_at / paused_at / archived_at.
    ("containers", "last_active_at"),
    ("containers", "paused_at"),
    ("containers", "archived_at"),
}
# (table, column) present in the MODELS but absent from the MIGRATED head:
MODELS_ONLY_ALLOW: set[tuple[str, str]] = set()
# table present on only one side (rare; e.g. a reflection-only artifact):
TABLE_ALLOW: set[str] = set()


def _flatten(schema: dict[str, set[str]]) -> set[tuple[str, str]]:
    return {(t, c) for t, cols in schema.items() for c in cols}


@pytest.mark.asyncio
async def test_models_match_migrated_head(migrated_db: str) -> None:
    from tests.integration.migrations._helpers import model_schema, reflect_db_schema

    models = model_schema()
    db = await reflect_db_schema(migrated_db)

    model_tables, db_tables = set(models), set(db)
    only_models_tables = model_tables - db_tables - TABLE_ALLOW
    only_db_tables = db_tables - model_tables - TABLE_ALLOW
    assert not only_models_tables, (
        f"tables in models but not migrated head: {sorted(only_models_tables)}"
    )
    assert not only_db_tables, f"tables in migrated head but not models: {sorted(only_db_tables)}"

    shared = model_tables & db_tables
    model_cols = _flatten({t: models[t] for t in shared})
    db_cols = _flatten({t: db[t] for t in shared})

    migrated_only = (db_cols - model_cols) - MIGRATED_ONLY_ALLOW
    models_only = (model_cols - db_cols) - MODELS_ONLY_ALLOW
    assert not migrated_only, (
        "columns in MIGRATED head but missing from models (schema drift): "
        f"{sorted(migrated_only)}"
    )
    assert not models_only, (
        "columns in MODELS but missing from migrated head (will break queries): "
        f"{sorted(models_only)}"
    )

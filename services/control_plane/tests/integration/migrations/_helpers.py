from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

# .../tests/integration/migrations/_helpers.py  → parents[3] == services/control_plane
_CP_DIR = Path(__file__).resolve().parents[3]


def alembic_script() -> ScriptDirectory:
    cfg = Config(str(_CP_DIR / "alembic.ini"))
    # script_location in the ini is CWD-relative; pin it absolutely so the gate
    # is runnable from anywhere.
    cfg.set_main_option("script_location", str(_CP_DIR / "control_plane" / "migrations"))
    return ScriptDirectory.from_config(cfg)


def head_revision() -> str:
    heads = alembic_script().get_heads()
    assert len(heads) == 1, f"expected one head, got {heads}"
    return heads[0]


def model_schema() -> dict[str, set[str]]:
    """Tables+columns declared by the SQLAlchemy models.

    Both modules share ONE MetaData (`tables.py` does
    `from control_plane.models_db import metadata`), so both must be imported to
    see the full 21-table schema.
    """
    import control_plane.models_db as models_db
    import control_plane.tables  # noqa: F401  # registers users/credentials/… onto the shared MetaData

    return {
        name: {col.name for col in table.columns}
        for name, table in models_db.metadata.tables.items()
    }


async def reflect_db_schema(url: str) -> dict[str, set[str]]:
    """Tables+columns actually present in the migrated DB, via Inspector."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            def _inspect(sync_conn) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
                insp = sa.inspect(sync_conn)
                return {
                    t: {c["name"] for c in insp.get_columns(t)}
                    for t in insp.get_table_names()
                    if t != "alembic_version"
                }

            return await conn.run_sync(_inspect)
    finally:
        await engine.dispose()

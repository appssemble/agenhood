#!/usr/bin/env sh
# 1. Ensure the "connectors" Postgres database exists (idempotent; works on
#    pre-existing volumes because initdb.d only runs on a fresh data directory).
# 2. Bring the schema to the latest Alembic revision.
# 3. Hand off to CMD (uvicorn).
#
# Runs from the image WORKDIR (/app/services/connectors), where alembic.ini
# and the migrations package resolve correctly.
set -e

# Single-source DB config: when CONNECTORS_DATABASE_URL is not provided, derive it
# from the canonical DATABASE_URL — same server + credentials, with the database
# name swapped to "connectors". Keeps one connection-string secret across the
# stack. An explicit CONNECTORS_DATABASE_URL still wins.
if [ -z "${CONNECTORS_DATABASE_URL:-}" ] && [ -n "${DATABASE_URL:-}" ]; then
  CONNECTORS_DATABASE_URL="${DATABASE_URL%/*}/connectors"
  export CONNECTORS_DATABASE_URL
fi

echo "==> entrypoint: ensure connectors database exists"
python - <<'PYEOF'
"""
Create the connectors database in the shared Postgres instance if it does not
already exist.  We connect to the administrative 'postgres' database (always
present) and issue CREATE DATABASE; catching DuplicateDatabaseError makes the
step fully idempotent — safe to run against an already-populated volume.

Connection parameters are parsed from CONNECTORS_DATABASE_URL, e.g.:
    postgresql+asyncpg://user:pass@host:5432/connectors
"""
import asyncio
import os
import urllib.parse

import asyncpg


def _quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ValueError("invalid database name")
    return '"' + identifier.replace('"', '""') + '"'


async def _ensure_db() -> None:
    raw = os.environ.get("CONNECTORS_DATABASE_URL", "")
    if not raw:
        print("CONNECTORS_DATABASE_URL not set — skipping DB creation")
        return

    # urllib.parse does not understand the SQLAlchemy dialect prefix.
    url = raw.replace("postgresql+asyncpg://", "postgresql://")
    p = urllib.parse.urlparse(url)
    host = p.hostname or "localhost"
    port = p.port or 5432
    user = p.username or "postgres"
    password = p.password or ""
    dbname = p.path.lstrip("/")  # e.g. "connectors"

    # Connect to the always-present administrative database, not the target DB
    # (which may not exist yet).  CREATE DATABASE cannot run inside a transaction
    # so asyncpg's auto-transaction is fine here — it issues each statement in
    # its own implicit transaction when not inside an explicit begin().
    conn = await asyncpg.connect(
        host=host, port=port, user=user, password=password, database="postgres"
    )
    try:
        await conn.execute(f"CREATE DATABASE {_quote_identifier(dbname)}")
        print(f"Database '{dbname}' created.")
    except asyncpg.exceptions.DuplicateDatabaseError:
        print(f"Database '{dbname}' already exists — skipping.")
    finally:
        await conn.close()


asyncio.run(_ensure_db())
PYEOF

echo "==> entrypoint: alembic upgrade head"
alembic upgrade head

exec "$@"

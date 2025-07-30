#!/usr/bin/env sh
# Bring the database schema to the latest revision before starting the app, so
# the schema never lags the running code. Without this, updating the code while
# the stack is already up (dev uses uvicorn --reload, which reloads Python but
# does NOT re-run `make dev`'s bootstrap) leaves the DB a migration behind and
# the app 500s on the first query that touches a new column/table.
#
# Idempotent: a no-op when the DB is already at head. Runs from the image
# WORKDIR (/app/services/control_plane), where alembic.ini + migrations resolve.
set -e

# Ensure the target database exists before migrating. With the bundled Postgres
# the DB is created by POSTGRES_DB on init, but against an external/managed
# Postgres (e.g. the Coolify deployment) it may not exist yet — so create it
# idempotently, the same way the connectors service does. Connects to the
# always-present "postgres" admin DB; a no-op if the DB already exists or if
# DATABASE_URL already targets "postgres".
echo "==> entrypoint: ensure control-plane database exists"
python - <<'PYEOF'
import asyncio
import os
import urllib.parse

import asyncpg


def _quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ValueError("invalid database name")
    return '"' + identifier.replace('"', '""') + '"'


async def _ensure_db() -> None:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        print("DATABASE_URL not set — skipping DB creation")
        return

    url = raw.replace("postgresql+asyncpg://", "postgresql://")
    p = urllib.parse.urlparse(url)
    host = p.hostname or "localhost"
    port = p.port or 5432
    user = p.username or "postgres"
    password = p.password or ""
    dbname = p.path.lstrip("/")
    if not dbname or dbname == "postgres":
        return  # nothing to create (already the admin DB)

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

# Idempotent seed: built-in templates, the seed tenant (limit defaults), and —
# when SEED_STAFF_EMAIL/PASSWORD are set — a staff (admin) login. The seed API
# key is only minted when SEED_API_KEY is explicitly set.
echo "==> entrypoint: seed"
python -m control_plane.seed

exec "$@"

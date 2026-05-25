#!/usr/bin/env bash
# Single-source DB config: parse POSTGRES_USER/PASSWORD/DB out of the canonical
# DATABASE_URL and hand off to the stock postgres entrypoint, so the bundled
# Postgres and the app services share ONE connection-string secret.
#
# DATABASE_URL is the SQLAlchemy async DSN, e.g.
#   postgresql+asyncpg://user:pass@postgres:5432/agentruntime
# Only parts BEFORE the '@' (user/pass) and the path (db) are read; the dialect
# prefix is irrelevant to the split. If POSTGRES_USER is already set, it wins
# (lets a caller override without touching the URL).
#
# NOTE: the password must not contain a literal '@' or ':' (it would break the
# naive split). Generators like `openssl rand -base64`/`token_hex` are safe;
# URL-encode any exotic password.
set -euo pipefail

if [ -n "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_USER:-}" ]; then
  noscheme="${DATABASE_URL#*://}"   # user:pass@host:5432/dbname?opts
  creds="${noscheme%%@*}"           # user:pass
  rest="${noscheme#*@}"             # host:5432/dbname?opts
  pathpart="${rest#*/}"             # dbname?opts
  POSTGRES_USER="${creds%%:*}"
  POSTGRES_PASSWORD="${creds#*:}"
  POSTGRES_DB="${pathpart%%\?*}"    # strip any ?query
  export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB
fi

exec docker-entrypoint.sh "$@"

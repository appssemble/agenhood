#!/usr/bin/env sh
# Bootstrap the dev stack: migrate DB, seed built-in templates, create login owner.
# Usage: bootstrap-dev.sh <compose-project> <env-file> <compose-file>...
set -eu

PROJECT="$1"; shift
ENV_FILE="$1"; shift
COMPOSE_FILES=""
for f in "$@"; do COMPOSE_FILES="$COMPOSE_FILES -f $f"; done

# Load DEV_* and ADMIN_API_KEY for the owner-creation request.
# shellcheck disable=SC1090
. "$ENV_FILE"

# shellcheck disable=SC2086
dc() { docker compose -p "$PROJECT" $COMPOSE_FILES --env-file "$ENV_FILE" "$@"; }

echo "==> Applying database migrations (alembic upgrade head)"
dc exec -T control-plane alembic upgrade head

echo "==> Seeding built-in drivers/templates"
dc exec -T control-plane python -m control_plane.seed

echo "==> Creating dev tenant + owner login (idempotent)"
PAYLOAD=$(cat <<JSON
{"name":"${DEV_TENANT_NAME}","owner":{"email":"${DEV_ADMIN_EMAIL}","name":"Dev Admin","password":"${DEV_ADMIN_PASSWORD}"}}
JSON
)
CODE=$(dc exec -T -e "PAYLOAD=${PAYLOAD}" -e "ADMIN_API_KEY=${ADMIN_API_KEY}" control-plane sh -c \
  'curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8443/admin/v1/tenants \
    -H "Authorization: Bearer $ADMIN_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"')

case "$CODE" in
  201) echo "    created." ;;
  409) echo "    already exists (ok)." ;;
  *)   echo "ERROR: tenant/owner creation returned HTTP $CODE" >&2; exit 1 ;;
esac

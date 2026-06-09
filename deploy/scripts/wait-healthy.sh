#!/usr/bin/env sh
# Poll the control plane /healthz (inside its container) until ready or timeout.
# Usage: wait-healthy.sh <compose-project> <env-file> <compose-file>... -- <timeout-seconds>
set -eu

PROJECT="$1"; shift
ENV_FILE="$1"; shift

COMPOSE_FILES=""
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
  COMPOSE_FILES="$COMPOSE_FILES -f $1"
  shift
done
if [ "${1:-}" = "--" ]; then shift; fi
TIMEOUT="${1:-90}"

# shellcheck disable=SC2086
dc() { docker compose -p "$PROJECT" $COMPOSE_FILES --env-file "$ENV_FILE" "$@"; }

echo "Waiting for control-plane /healthz (timeout ${TIMEOUT}s)..."
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
  if dc exec -T control-plane curl -fs http://localhost:8443/healthz >/dev/null 2>&1; then
    echo "control-plane is healthy."
    exit 0
  fi
  i=$((i + 2))
  sleep 2
done

echo "ERROR: control-plane did not become healthy in ${TIMEOUT}s." >&2
echo "Hint: run 'make logs' to inspect." >&2
exit 1

#!/usr/bin/env sh
# Post-`make dev` smoke check: control plane healthy + console serving.
set -eu

PROJECT="agenhood-dev"
echo "==> control-plane /healthz"
docker compose -p "$PROJECT" \
  -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
  --env-file deploy/.env.dev \
  exec -T control-plane curl -fs http://localhost:8443/healthz

echo ""
echo "==> console http://localhost:5173"
curl -fsS -o /dev/null -w "console HTTP %{http_code}\n" http://localhost:5173/

echo "Smoke OK."

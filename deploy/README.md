# Deploy: single-host topology

This brings up the full agent runtime on one host (spec §10): Traefik, the web
console, the control plane, Postgres, the egress proxy, and SearXNG, across the
three networks. Agent containers are created at runtime by the control plane
onto `agent-runtime-internal` only.

## Local dev (hot-reload)

For day-to-day development use the repo-root `make dev` / `make stop` instead of
the production compose below. It applies `docker-compose.dev.yml` on top of this
file under the `agenhood-dev` project: the control plane runs with `--reload`,
the console runs a Vite dev server on `http://localhost:5173` (proxying `/v1` and
`/admin` to the control plane), and Traefik is not started. Secrets come from the
committed, insecure `deploy/.env.dev`.

## Prerequisites

- Docker + docker compose v2.
- The agent image built (Unit 1): `make image` → `agent-runtime:v0.1.0`.
- **After bumping the agent image / opencode version**, regenerate and commit the
  model catalog: `make models-catalog` (Docker required; set
  `MODELS_CATALOG_CODEX_AUTH=/path/to/codex-auth.json` to include OpenAI
  subscription models) and commit the updated
  `services/control_plane/control_plane/model_catalog.json`.
- The control-plane and web-console images buildable (Units 2 / 6); compose
  builds them from `../services/control_plane` and `../web/console`.

## First run

```bash
cp deploy/.env.example deploy/.env
# Edit deploy/.env: set CREDENTIAL_ENCRYPTION_KEY, ADMIN_API_KEY,
# POSTGRES_PASSWORD, SEARXNG_SECRET, PUBLIC_HOST. Generators are in .env.example.
# Optional: configure OAUTH_SUBSCRIPTION_* and OPENAI_OAUTH_* for ChatGPT subscription auth.

docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
docker compose -f deploy/docker-compose.yml ps
```

## Verify (exit criteria, spec §1.3 #5 / §10 / §13 Phase 5)

1. **Control plane is healthy (DB reachable):**
   ```bash
   curl -ks https://$PUBLIC_HOST/v1/healthz    # -> {"status":"ok"}
   ```
2. **Same-origin routing:** `https://$PUBLIC_HOST/` serves the console SPA;
   `https://$PUBLIC_HOST/v1/...` hits the control plane, same origin, so the
   session cookie and SSE work without CORS.
3. **Egress chokepoint (the important one):** run the automated proof:
   ```bash
   cd services/control_plane
   python -m pytest tests/test_networking_integration.py -v -m integration
   ```
   This brings up the internal+egress networks and the proxy, attaches a probe
   to the internal network only, and asserts: direct egress fails (no gateway),
   the metadata endpoint and RFC1918 are blocked via the proxy, and an allowed
   public host succeeds and is logged.
4. **Search works through SearXNG:**
   ```bash
   docker compose -f deploy/docker-compose.yml exec searxng \
     curl -s "http://localhost:8080/search?q=test&format=json" | head -c 200
   ```
   Returns JSON (proves `formats: [json]` is active).

## Logs (observability, spec §12)

```bash
docker compose -f deploy/docker-compose.yml logs --since 10m control-plane | jq
docker compose -f deploy/docker-compose.yml logs --since 10m egress-proxy | jq
```

Both emit `{ts, level, msg, ...}` JSON lines; the egress proxy logs every
allow/block decision with host + reason.

## Networks (spec §8.1)

| Network | internal? | Members | Purpose |
|---------|-----------|---------|---------|
| `default` | no | traefik, control-plane, web-console, postgres | public API + DB |
| `agent-runtime-internal` | **yes** (no gateway) | control-plane, egress-proxy, searxng, **agents** | shim↔CP, agent→proxy, agent→search |
| `agent-runtime-egress` | no | egress-proxy, searxng **only** | the only outbound path |

Agents attach to `agent-runtime-internal` **only**, so their sole route out is
the egress proxy (`HTTP_PROXY`/`HTTPS_PROXY=http://egress-proxy:8888`).

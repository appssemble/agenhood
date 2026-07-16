# Coolify deployment runbook

## Prerequisites
- Registry resource deployed (deploy/registry/) and reachable at https://registry.example.com.
- Agent image pushed multi-arch: `registry.example.com/agent-runtime:<AGENT_IMAGE_TAG>`.
- Control-plane env has `AGENT_REGISTRY` + `AGENT_REGISTRY_USERNAME` + `AGENT_REGISTRY_PASSWORD`
  (the control plane pulls the private image with these — no host `docker login` needed; see Task 6).
- Provisioning pulls: `AGENT_IMAGE_PULL_POLICY=if-not-present` (default) makes creates
  skip the registry when the image is already on the host; a background sweep pre-pulls
  `AGENT_IMAGE_TAG` every `IMAGE_PREPULL_INTERVAL_SECONDS` (600) so version bumps are
  downloaded outside user-facing requests. Set `AGENT_IMAGE_PULL_POLICY=always` only if
  you deliberately ride a moving tag and want every create to force-pull.

## Create the app resource
- New Resource → Docker Compose.
- Base Directory: `/`  (build contexts use `../`, so the repo root must be the build root).
- Compose file: `/deploy/docker-compose.coolify.yml`.
- Paste env from `deploy/.env.coolify.example` (fill real secrets).
- Set the domain `agent.example.com` on the `reverse-proxy` service (container port 80).
- Confirm the control-plane service has the Docker socket mount allowed.
- Deploy.

## Proxy/SearXNG config sanity (baked, not bind-mounted)
The declawed Traefik and SearXNG ship their config baked into their images
(`deploy/traefik/Dockerfile`, `deploy/searxng/Dockerfile`) — there are NO repo bind
mounts for Coolify to misresolve. Confirm the files are actually inside the running
containers (substitute the real Coolify container names):
```bash
docker exec <reverse-proxy> stat -c %F /etc/traefik/traefik.yml   # -> regular file (NOT directory)
docker exec <reverse-proxy> sh -c 'head /etc/traefik/dynamic.yml' # -> the routing YAML (routers/services)
docker exec <searxng>       ls    /etc/searxng/settings.yml       # -> present (~978 B)
```
If any prints `directory` or is missing, the image build did not pick up the config
— rebuild the image; do NOT fall back to repo bind mounts.

## Network sanity (the security-critical check)
After deploy, confirm the chokepoint survived Coolify's network wrapping:
```bash
docker network inspect agent-runtime-internal --format '{{.Internal}}'   # -> true
docker network inspect agent-runtime-internal --format '{{.Name}}'       # -> agent-runtime-internal (literal, not project-prefixed)
```

## Verify control-plane health through the proxy chain

Run:
```bash
curl -ks https://agent.example.com/healthz     # -> {"status":"ok"}
```
Expected: `{"status":"ok"}` (proves Coolify proxy → declawed Traefik → control-plane path routing works).

## Verify single-origin path routing

Run:
```bash
curl -ks -o /dev/null -w "console=%{http_code}\n" https://agent.example.com/        # 200 (SPA)
curl -ks -o /dev/null -w "api=%{http_code}\n"     https://agent.example.com/healthz  # 200 (control-plane)
```
Expected: both `200`, same origin.

## Verify the chokepoint network is intact

Run the two `docker network inspect` commands from the runbook.
Expected: `Internal=true` and `Name=agent-runtime-internal`. If `Internal=false`, the egress isolation is broken — STOP and fix the compose `networks` block before exposing the app.

## Verify agent provisioning pulls from the registry and runs

Create one container via the API (admin/seed creds), then:
```bash
docker ps --filter "label=agent-runtime.tenant_id" --format '{{.Image}} {{.Names}}'
```
Expected: an agent container running `registry.example.com/agent-runtime:<tag>` — proves the daemon pulled the registry image and attached it to the internal network.

## Verify egress isolation from inside an agent

Run:
```bash
AGENT=$(docker ps --filter "label=agent-runtime.tenant_id" -q | head -1)
docker exec "$AGENT" sh -c 'curl -s -m 5 https://example.com -o /dev/null && echo DIRECT_OK || echo DIRECT_BLOCKED'
docker exec "$AGENT" sh -c 'curl -s -m 5 -x http://egress-proxy:8888 https://example.com -o /dev/null && echo PROXY_OK || echo PROXY_FAIL'
```
Expected: `DIRECT_BLOCKED` (no gateway on the internal network) and `PROXY_OK` (only path out is the egress proxy).

# Agenhood

Self-hosted infrastructure for running a fleet of sandboxed, long-lived AI agents.

Early work in progress. Not yet usable in production.

## What's here so far

- Multi-tenant control-plane API (FastAPI + Postgres) with tenant/user auth and API keys
- Agents run as sandboxed, resource-limited Docker containers with a persistent workspace
- Task submission with live streaming (Server-Sent Events) of agent output
- Lifecycle management: pause, resume, archive, and automatic idle-pause / wake-on-task
- A web console (React + TypeScript + Vite) for browsing the fleet and running tasks

Not yet built: workflows, scheduling, skills/MCP tooling, Git-backed workspace backup,
usage analytics, and the production Compose topology (Traefik, egress proxy, SearXNG).

## Architecture

```
 Web console (React SPA)
        |  REST + SSE
        v
 Control plane (FastAPI) ---- Postgres
        |
        |  Docker SDK: provision / drive
        v
 Agent container (shim + driver)
```

- **`agentcore`** — shared Python library: agent/task models, the driver & tool
  interfaces, the provider-agnostic LLM client, event schema, and sandbox limits.
- **Shim** — PID-1 inside every agent container. Runs the selected driver and
  streams events back to the control plane.
- **Control plane** — FastAPI service. Owns the public API, authenticates
  principals (tenant API keys, user sessions), persists to Postgres, and drives
  the Docker daemon to provision/supervise agent containers.
- **Console** — a React + TypeScript + Vite SPA; a plain client of the
  control-plane API (login, fleet grid, container detail, task submission,
  live task viewer, task history).

## Planned components

- `agentcore` — driver + LLM abstractions shared by the services
- `control-plane` — API that provisions and supervises agents in Docker
- `console` — web UI

## Quick start

Prerequisites: Docker (daemon running).

```bash
git clone https://github.com/appssemble/agenhood.git
cd agenhood
cp deploy/.env.example deploy/.env   # fill in DB creds, etc. (see deploy/)
make dev
```

This builds and starts Postgres, the control plane, and the console:

```
Console:       http://localhost:5173
Control plane: http://localhost:8443/v1
```

Create a tenant/user via the control-plane API (see the auth/tenants routers),
then log in at the console URL above.

## License

MIT (see `LICENSE`).

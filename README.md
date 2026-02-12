# Agenhood

Self-hosted infrastructure for running a fleet of sandboxed, long-lived AI agents.

Early work in progress. Not yet usable in production.

## Features

- **Fleet** — agents run as sandboxed, resource-limited Docker containers with a persistent
  workspace. Lifecycle management (pause, resume, archive) plus automatic idle-pause and
  wake-on-task.
- **Tasks** — submit a prompt and stream the agent's output live over Server-Sent Events.
- **Pluggable drivers** — one identical API, swappable execution engines (vanilla tool-use
  loop, Opencode, Codex, Claude Code) registered per agent.
- **Multi-tenant auth** — tenant/user accounts, API keys, and OAuth connect flows for
  Claude/ChatGPT subscription auth, plus SSH-backed Git remotes for workspace backup.
- **Skills & templates** — reusable, Git-sourced skills and container templates agents can
  be provisioned from.
- **Scheduling** — schedule a prompt to fire once or on a recurring cadence; a calendar view
  and a scheduled-tasks list show upcoming and past runs.
- A web console (React + TypeScript + Vite) for browsing the fleet, running tasks, and
  managing schedules.

Not yet built: workflows, MCP tooling, Git-backed linked-repo file browsing, usage
analytics, and the production Compose topology (Traefik, egress proxy, SearXNG).

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
  principals (tenant API keys, user sessions), persists to Postgres, drives
  the Docker daemon to provision/supervise agent containers, and runs the
  background scheduler sweep that fires due scheduled tasks.
- **Console** — a React + TypeScript + Vite SPA; a plain client of the
  control-plane API (login, fleet grid, container detail, task submission,
  live task viewer, task history, scheduled-tasks calendar).

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

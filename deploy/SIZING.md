# Resource sizing

## Base services (steady-state RAM, approximate)
| Service        | RAM    | Notes |
|----------------|--------|-------|
| postgres       | ~256MB | two small DBs (agentruntime + connectors) |
| control-plane  | ~256MB | FastAPI + docker SDK |
| connectors     | ~192MB | FastAPI |
| web-console    | ~32MB  | nginx static |
| searxng        | ~128MB | |
| egress-proxy   | ~64MB  | |
| reverse-proxy  | ~64MB  | traefik, file provider |
| **base total** | **~1.0–1.3GB** | round up to **1.5GB** headroom |

## Agents (the variable cost)
Each agent is capped by a per-variant default (`mem_limit`/`cpus`, hard caps),
tiered by `image_variant`:
- `AGENT_MEM_LIMIT_SLIM=2g`, `AGENT_CPUS_SLIM=1` — non-browser workloads (default).
- `AGENT_MEM_LIMIT_FULL=4g`, `AGENT_CPUS_FULL=2` — browser-heavy (Chromium) agents (default).

A caller can also override either value per container (bounded by
`AGENT_MEM_LIMIT_MIN`/`MAX` and `AGENT_CPUS_MIN`/`MAX`, default `256m`-`8g` /
`0.25`-`4`) at create time or later via `PATCH /containers/{id}/resources`
(live, no restart) — size the VM for your configured `_MAX` bound if tenants
are allowed to raise containers to it, not just the tiered defaults below.

## Formula
    VM_RAM   = 1.5GB (base) + N_max_concurrent_agents × <largest configured mem cap in use>
    VM_CPU   = ~2 (base) + N_max_concurrent_agents × <largest configured cpu cap in use>  (CPU oversubscribes safely; size for steady, not peak)
    VM_DISK  = OS/images (~10GB) + agent image versions (~3GB each kept) + agent /workspace volumes + pg data

## Examples
| N agents | mem cap in use | VM RAM target |
|----------|------------------|---------------|
| 3        | 2g               | ~7.5GB → 8GB  |
| 5        | 2g               | ~11.5GB → 12GB |
| 5        | 4g               | ~21.5GB → 24GB |

## Colima
Set the VM to the target explicitly, e.g.:
    colima start --cpu 4 --memory 12 --disk 60
Resize later with `colima stop && colima start --memory <new>`. The agent caps are
enforced inside the VM; do not over-allocate the VM beyond what the host can spare.

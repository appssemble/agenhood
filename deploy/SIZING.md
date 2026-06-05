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
Each agent is capped by `AGENT_MEM_LIMIT` (hard `mem_limit`). Recommended start:
- `AGENT_MEM_LIMIT=2g`, `AGENT_CPUS=1` for non-browser workloads.
- Raise to `4g` / `2` CPU only for browser-heavy (Chromium) agents.

## Formula
    VM_RAM   = 1.5GB (base) + N_max_concurrent_agents × AGENT_MEM_LIMIT
    VM_CPU   = ~2 (base) + N_max_concurrent_agents × AGENT_CPUS  (CPU oversubscribes safely; size for steady, not peak)
    VM_DISK  = OS/images (~10GB) + agent image versions (~3GB each kept) + agent /workspace volumes + pg data

## Examples
| N agents | AGENT_MEM_LIMIT | VM RAM target |
|----------|------------------|---------------|
| 3        | 2g               | ~7.5GB → 8GB  |
| 5        | 2g               | ~11.5GB → 12GB |
| 5        | 4g               | ~21.5GB → 24GB |

## Colima
Set the VM to the target explicitly, e.g.:
    colima start --cpu 4 --memory 12 --disk 60
Resize later with `colima stop && colima start --memory <new>`. The agent caps are
enforced inside the VM; do not over-allocate the VM beyond what the host can spare.

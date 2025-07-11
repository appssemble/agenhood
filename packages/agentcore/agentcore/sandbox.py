"""Single chokepoint for launching UNTRUSTED, agent-controlled processes.

The shim runs as root inside a locked-down container and drops to an
unprivileged ``agent`` uid for every untrusted leaf process (driver CLIs, the
vanilla bash/python tools, workspace git). Routing all such spawns through
``spawn_untrusted`` guarantees a uniform privilege drop + a default-deny
environment allowlist, so the agent can never read SHIM_TOKEN or other
shim-only secrets from an inherited environment.

When the process is not root (local dev, pytest) the drop is a no-op so the
child runs as the current user — behaviour is otherwise identical.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

AGENT_UID = int(os.environ.get("AGENT_UID", "1000"))
AGENT_GID = int(os.environ.get("AGENT_GID", "1000"))
AGENT_HOME = os.environ.get("AGENT_HOME", "/home/agent")

# StreamReader line ceiling for untrusted children. Driver CLIs emit one JSON
# event per line and can embed large shell output on a single line; asyncio's
# 64 KiB default makes readline() raise ValueError past that, crashing the read
# loop. 8 MiB tolerates realistic agent output (worst case bounded by pids/mem).
STREAM_LINE_LIMIT = 8 * 1024 * 1024

# Default-deny: only these names are forwarded to untrusted children. Secrets
# the shim holds (SHIM_TOKEN, CONTAINER_ID, TENANT_ID, SHIM_MAX_WORKERS) are
# never listed. Drivers add their own vars (API keys, HOME redirect) via `extra`.
_ENV_ALLOW = (
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SEARCH_PROVIDER_URL",
    # The image sets NODE_OPTIONS=--require <node-proxy preload> so Node's
    # built-in fetch honors the egress proxy; it must survive the default-deny
    # filter or workspace *.mjs fetch() fails with EAI_AGAIN (curl still works).
    "NODE_OPTIONS",
)


def build_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a default-deny environment for an untrusted child.

    Starts from the allowlist, forces HOME to the agent's writable home (so the
    child never sees root's HOME), then applies driver-supplied `extra` (which
    may legitimately override HOME, e.g. CODEX_HOME redirect).
    """
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["HOME"] = AGENT_HOME
    if extra:
        env.update(extra)
    return env


def drop_kwargs() -> dict[str, Any]:
    """subprocess kwargs that drop to the agent uid — only when we are root."""
    if os.geteuid() == 0:
        return {"user": AGENT_UID, "group": AGENT_GID, "extra_groups": []}
    return {}


def ensure_agent_dir(path: str, mode: int = 0o700) -> None:
    """Create `path` (and parents) and, when root, chown it to the agent uid.

    Dirs the root shim pre-creates under the agent-owned `.agent-state` would
    otherwise be root-owned and unwritable by the dropped child.
    """
    os.makedirs(path, mode=mode, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(path, AGENT_UID, AGENT_GID)


def chown_to_agent(path: str) -> None:
    """chown a single path to the agent uid when root (no-op otherwise)."""
    if os.geteuid() == 0:
        os.chown(path, AGENT_UID, AGENT_GID)


def makedirs_agent(path: str, mode: int = 0o755) -> None:
    """Create `path` and any missing parents, chowning newly-created dirs to the
    agent uid when root so the dropped agent can write inside them."""
    if not path:
        return
    missing: list[str] = []
    p = path
    while p and not os.path.isdir(p):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    os.makedirs(path, mode=mode, exist_ok=True)
    if os.geteuid() == 0:
        for d in missing:
            try:
                os.chown(d, AGENT_UID, AGENT_GID)
            except FileNotFoundError:
                pass


async def spawn_untrusted(
    argv: list[str], *, cwd: str, env: dict[str, str], **kwargs: Any
) -> asyncio.subprocess.Process:
    """Spawn an untrusted child: drop to the agent uid (when root) + given env.

    The privilege-drop kwargs (``user``/``group``/``extra_groups``) always take
    precedence over anything in ``**kwargs`` — a caller can never override the
    uid the child drops to.
    """
    return await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, **{"limit": STREAM_LINE_LIMIT, **kwargs, **drop_kwargs()}
    )


def terminate(proc: Any) -> None:
    """Best-effort SIGTERM to an untrusted child — never raises.

    The child runs under the agent uid; signalling it from the (root) parent
    needs CAP_KILL, without which ``kill()`` across uids returns EPERM. Swallow
    that — and a benign race where the child already exited — so process
    teardown can neither crash a driver nor mask the error that triggered it.
    """
    try:
        proc.terminate()
    except (PermissionError, ProcessLookupError):
        pass

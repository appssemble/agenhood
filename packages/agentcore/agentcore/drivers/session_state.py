"""On-disk session-state persistence, shared by all drivers.

Each driver's continuation data (a native CLI session id, or — for vanilla,
which has no CLI of its own — the full message transcript) lives as one JSON
file per session under the container's persistent workspace volume, not in
the control plane's database. Disk presence is what decides whether a session
is actually resumable (driver-sessions spec §3): the database only tracks
which tasks share a session_id, never a copy of the driver's state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agentcore import sandbox


def session_state_path(workspace: str, driver: str, session_id: str) -> str:
    """Path to a session's state file under the driver's per-workspace state dir."""
    return str(Path(workspace) / ".agent-state" / driver / "sessions" / f"{session_id}.json")


def read_session_state(workspace: str, driver: str, session_id: str) -> dict[str, Any] | None:
    """Return the stored state dict, or None if missing, unreadable, or corrupt."""
    path = session_state_path(workspace, driver, session_id)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def write_session_state(
    workspace: str, driver: str, session_id: str, state: dict[str, Any]
) -> None:
    """Persist `state`, creating agent-owned parent dirs as needed.

    Recreates rather than truncates in place: a prior task chowned this file
    to the agent uid, and the sandbox grants root no CAP_FOWNER, so chmod on a
    foreign-owned file would EPERM (same fix as codex.py's write_auth_json /
    opencode.py's write_auth_json). Unlinking first (root has DAC_OVERRIDE on
    the agent-owned parent dir) lets the fresh file be root-owned, so chmod
    succeeds; chown_to_agent then hands it back to the agent uid.
    """
    path = Path(session_state_path(workspace, driver, session_id))
    sandbox.ensure_agent_dir(str(path.parent))
    path.unlink(missing_ok=True)
    path.write_text(json.dumps(state))
    os.chmod(path, 0o600)
    sandbox.chown_to_agent(str(path))

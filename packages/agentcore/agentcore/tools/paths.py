from __future__ import annotations

import os

RESERVED_DIRS = (".agent-runtime", ".agent-state")


class PathError(ValueError):
    """Raised when a tool path escapes the workspace or hits a reserved dir."""


def safe_resolve(workspace: str, path: str) -> str:
    """Resolve `path` against `workspace`, following symlinks on existing parents.

    Returns an absolute path guaranteed to live inside `workspace` and outside
    any reserved directory. Raises PathError otherwise.
    """
    ws = os.path.realpath(workspace)
    raw = path if os.path.isabs(path) else os.path.join(ws, path)
    # realpath resolves symlinks in every existing path component; for a
    # not-yet-created leaf it resolves the existing parent and appends the leaf.
    resolved = os.path.realpath(raw)

    ws_prefix = ws.rstrip("/") + "/"
    if resolved != ws and not resolved.startswith(ws_prefix):
        raise PathError(f"path {path!r} resolves outside the workspace")

    rel = os.path.relpath(resolved, ws)
    first = rel.split(os.sep, 1)[0]
    if first in RESERVED_DIRS:
        raise PathError(f"path {path!r} is inside the reserved {first}/ directory")

    return resolved

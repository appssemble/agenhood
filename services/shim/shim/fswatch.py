from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable

from watchfiles import awatch

RUNTIME_DIR = ".agent-runtime"

_OP_BY_CHANGE = {1: "create", 2: "modify", 3: "delete"}


def classify_change(change_value: int) -> str:
    return _OP_BY_CHANGE.get(change_value, "modify")


def iter_relevant(
    raw_changes: Iterable[tuple[int, str]], workspace: str
) -> list[tuple[str, str]]:
    """Map raw watchfiles changes to (operation, relative_path), dropping the
    reserved .agent-runtime/ directory."""
    ws = os.path.realpath(workspace)
    out: list[tuple[str, str]] = []
    for change_value, abspath in raw_changes:
        rel = os.path.relpath(os.path.realpath(abspath), ws)
        if rel == RUNTIME_DIR or rel.startswith(RUNTIME_DIR + os.sep):
            continue
        out.append((classify_change(change_value), rel))
    return out


async def watch_workspace(
    workspace: str,
    on_change: Callable[[str, str, int], Awaitable[None]],
    stop: asyncio.Event,
) -> None:
    """Await file changes under `workspace` and invoke on_change(path, op, size)
    until `stop` is set. size is 0 for deletes (file no longer exists)."""
    async for changes in awatch(workspace, stop_event=stop):
        for op, rel in iter_relevant(changes, workspace):
            full = os.path.join(os.path.realpath(workspace), rel)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            await on_change(rel, op, size)

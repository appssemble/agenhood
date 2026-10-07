"""Hot spare: one warm ``codex app-server`` per container, ready for the next task.

Opening a thread makes codex open and warm its connection to OpenAI, which takes
about a second. A spare is an app-server with a thread already open, so a task
that claims it only sends its turn (measured 2026-10-07: 2.5 s median for a
simple task against 3.8 s cold).

A spare is built from the last task's settings and fits only a task whose
settings hash to the same fingerprint. The shim decides whether the container
has room for one (``set_capacity_check``). A spare left unused for
``SPARE_MAX_AGE_SECONDS`` is stopped and not replaced; the next task starts
cold and builds a new one after it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

SPARE_MAX_AGE_SECONDS = 600.0
MAX_BUILD_FAILURES = 3
THREAD_START_TIMEOUT_SECONDS = 60.0

StartFn = Callable[..., Awaitable[Any]]


def fingerprint(*parts: Any) -> str:
    """Stable hash of everything that shapes a thread before its first turn."""
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SpareRecipe:
    cmd: list[str]
    cwd: str
    env: dict[str, str]
    thread_params: dict[str, Any]
    fingerprint: str


@dataclass
class Spare:
    client: Any
    thread_id: str
    fingerprint: str


class SparePool:
    """Holds at most one spare. Built by ``refill``, taken by ``claim``, stopped
    when it expires, when settings change, or for good by ``close``."""

    def __init__(self, start: StartFn, *, max_age: float = SPARE_MAX_AGE_SECONDS) -> None:
        self._start = start
        self._max_age = max_age
        self._recipe: SpareRecipe | None = None
        self._spare: Spare | None = None
        self._building: asyncio.Task[None] | None = None
        self._building_fingerprint: str | None = None
        self._expiry: asyncio.TimerHandle | None = None
        self._failures = 0
        self._has_capacity: Callable[[], bool] | None = None
        self._closed = False

    def set_capacity_check(self, check: Callable[[], bool]) -> None:
        self._has_capacity = check

    def remember(self, recipe: SpareRecipe | None) -> None:
        """Settings for the next spare. None turns spares off and drops the current one."""
        previous = self._recipe.fingerprint if self._recipe else None
        if self._closed:
            return
        current = recipe.fingerprint if recipe else None
        if current != previous:
            self._failures = 0
        self._recipe = recipe
        if recipe is None:
            self._drop()

    async def claim(self, fp: str) -> tuple[Spare | None, str]:
        """Take the spare if it fits: ``(spare, "hit")``, else ``(None, reason)``."""
        if self._building is not None:
            if self._building_fingerprint != fp:
                self._drop()
                return None, "settings_changed"
            await asyncio.gather(asyncio.shield(self._building), return_exceptions=True)
        spare = self._take()
        if spare is None:
            return None, "warming_failed" if self._failures else "none"
        if spare.fingerprint != fp:
            _discard(spare)
            return None, "settings_changed"
        if not spare.client.alive:
            _discard(spare)
            return None, "dead"
        return spare, "hit"

    def refill(self) -> None:
        """Build a spare if spares are on, none exists, and the container has room."""
        recipe = self._recipe
        if (
            self._closed
            or recipe is None
            or self._spare is not None
            or self._building is not None
            or self._failures >= MAX_BUILD_FAILURES
            or self._has_capacity is None
            or not self._has_capacity()
        ):
            return
        self._building_fingerprint = recipe.fingerprint
        self._building = asyncio.create_task(self._build(recipe))

    async def ready(self) -> None:
        """Wait until no spare is being built."""
        if self._building is not None:
            await asyncio.gather(asyncio.shield(self._building), return_exceptions=True)

    async def close(self) -> None:
        """Stop the spare and any build in progress, and build no more."""
        self._closed = True
        self._recipe = None
        building = self._building
        self._drop()
        if building is not None:
            await asyncio.gather(building, return_exceptions=True)

    def _take(self) -> Spare | None:
        spare, self._spare = self._spare, None
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        return spare

    def _drop(self) -> None:
        if self._building is not None:
            self._building.cancel()
            self._building = None
        spare = self._take()
        if spare is not None:
            _discard(spare)

    def _expire(self) -> None:
        self._expiry = None
        self._drop()

    async def _build(self, recipe: SpareRecipe) -> None:
        client = None
        try:
            client = await self._start(recipe.cmd, cwd=recipe.cwd, env=recipe.env)
            started = await client.request(
                "thread/start", recipe.thread_params, timeout=THREAD_START_TIMEOUT_SECONDS
            )
            thread_id = started["thread"]["id"]
        except asyncio.CancelledError:
            if client is not None:
                client.abort()
            raise
        except Exception:  # noqa: BLE001 - a failed spare only costs the next task its warm start
            self._failures += 1
            if client is not None:
                client.abort()
            return
        finally:
            if self._building is asyncio.current_task():
                self._building = None
        self._failures = 0
        self._spare = Spare(client=client, thread_id=thread_id, fingerprint=recipe.fingerprint)
        self._expiry = asyncio.get_running_loop().call_later(self._max_age, self._expire)


def _discard(spare: Spare) -> None:
    # A thread writes no rollout before its first turn, so stopping codex leaves no thread behind.
    spare.client.abort()

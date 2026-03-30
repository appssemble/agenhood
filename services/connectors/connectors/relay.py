from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from connectors.rendering import TranscriptRenderer


class _ProviderLike(Protocol):
    async def post_initial(
        self, token: str, origin_ref: dict[str, Any], body: str
    ) -> dict[str, Any]: ...

    async def update_message(
        self, token: str, handle: dict[str, Any], body: str
    ) -> None: ...


async def run_relay(
    *,
    events: AsyncIterator[dict[str, Any]],
    provider: _ProviderLike,
    token: str,
    origin_ref: dict[str, Any],
    surface: list[str],
    coalesce_ms: int,
    save_progress: Callable[[int, str], Awaitable[None]],
    handle: dict[str, Any] | None = None,
    on_handle: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    """Consume task events, edit one provider message in place, persist progress.

    `handle` may be supplied to resume an existing delivery (skip the initial post).
    `on_handle` is called once with the provider message handle right after the
    initial post, allowing callers to persist the handle for later resumption.
    """
    renderer = TranscriptRenderer(surface=surface)
    if handle is None:
        handle = await provider.post_initial(token, origin_ref, "🤖 working…")
        if on_handle is not None:
            await on_handle(handle)
    last_flush = 0.0
    last_seq = 0
    pending = False

    async for ev in events:
        last_seq = int(ev.get("seq", last_seq))
        terminal = renderer.ingest(ev)
        pending = True
        now = time.monotonic() * 1000
        if terminal or (now - last_flush) >= coalesce_ms:
            await provider.update_message(token, handle, renderer.render())
            await save_progress(last_seq, "done" if terminal else "streaming")
            last_flush = now
            pending = False
        if terminal:
            return

    if pending:
        await provider.update_message(token, handle, renderer.render())
    # Stream ended without a terminal status — mark done so it is not retried forever.
    await save_progress(last_seq, "done")

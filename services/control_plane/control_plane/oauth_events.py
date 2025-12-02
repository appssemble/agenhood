"""In-process pub/sub for OAuth connection status (SSE emission, spec §5.2.1).

One asyncio.Queue per connection_id. The poller publishes terminal status; the
SSE endpoint drains the queue. In multi-replica deploys the SSE handler also
falls back to polling oauth_connections.status from the DB.
"""
from __future__ import annotations

import asyncio


class OAuthEventBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[str]] = {}

    def register(self, connection_id: str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._queues[connection_id] = q
        return q

    def unregister(self, connection_id: str) -> None:
        self._queues.pop(connection_id, None)

    def publish(self, connection_id: str, status: str) -> None:
        q = self._queues.get(connection_id)
        if q is not None:
            q.put_nowait(status)

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class ControlPlaneClient:
    def __init__(self, *, base_url: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, transport=self._transport, timeout=30  # type: ignore[arg-type]
        )

    async def submit_task(
        self, *, container_id: str, api_key: str, prompt: str, metadata: dict[str, Any]
    ) -> str:
        async with self._client() as c:
            resp = await c.post(
                f"/v1/containers/{container_id}/tasks",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"prompt": prompt, "metadata": metadata},
            )
            resp.raise_for_status()
            return str(resp.json()["task_id"])

    async def stream_events(
        self, *, container_id: str, task_id: str, api_key: str, after_seq: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        async with self._client() as c:
            async with c.stream(
                "GET",
                f"/v1/containers/{container_id}/tasks/{task_id}/events",
                params={"after_seq": after_seq},
                headers={"Authorization": f"Bearer {api_key}",
                         "Accept": "text/event-stream"},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw:
                        continue
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue

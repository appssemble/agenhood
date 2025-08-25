from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentcore.models import ShimTaskRequest


class ShimError(Exception):
    """Any non-success shim response other than the modeled ones."""


class ShimTooManyTasks(ShimError):
    """Shim returned 429 — at max_workers."""


class ShimGitConflict(ShimError):
    """Shim returned 409 — e.g. rollback while a task is running."""


class ShimGitNotFound(ShimError):
    """Shim returned 404 — e.g. unknown snapshot sha."""


class ShimClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=timeout
        )

    async def __aenter__(self) -> ShimClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def readyz(self) -> bool:
        try:
            r = await self._client.get("/readyz")
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    async def submit_task(self, req: ShimTaskRequest) -> dict[str, Any]:
        r = await self._client.post("/tasks", json=req.model_dump(by_alias=True))
        if r.status_code == 429:
            raise ShimTooManyTasks()
        if r.status_code >= 400:
            raise ShimError(f"shim POST /tasks -> {r.status_code}: {r.text}")
        return r.json()  # type: ignore[no-any-return]

    async def get_task(self, task_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/tasks/{task_id}")
        if r.status_code == 404:
            raise ShimError("task not found on shim")
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        r = await self._client.post(f"/tasks/{task_id}/cancel")
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def stream_events(self, task_id: str, after_seq: int | None) -> AsyncIterator[bytes]:
        params: dict[str, str] = {}
        if after_seq is not None:
            params["after_seq"] = str(after_seq)
        async with self._client.stream(
            "GET", f"/tasks/{task_id}/events", params=params, timeout=None
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                yield line.encode("utf-8")

    async def list_files(self, prefix: str | None) -> dict[str, Any]:
        params: dict[str, str] = {"prefix": prefix} if prefix else {}
        r = await self._client.get("/files", params=params)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def download_file(self, path: str) -> httpx.Response:
        r = await self._client.get("/files/raw", params={"path": path})
        r.raise_for_status()
        return r

    async def upload_file(self, path: str, content: bytes) -> None:
        r = await self._client.put("/files/raw", params={"path": path}, content=content)
        r.raise_for_status()

    async def delete_file(self, path: str) -> None:
        r = await self._client.delete("/files/raw", params={"path": path})
        r.raise_for_status()

    async def download_archive(self) -> AsyncIterator[bytes]:
        async with self._client.stream(
            "GET", "/files/archive", timeout=None
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk

    # ---- Git (workspace git rollback spec) -------------------------------

    async def git_status(self) -> dict[str, Any]:
        r = await self._client.get("/git/status")
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def git_log(self, limit: int = 200) -> dict[str, Any]:
        r = await self._client.get("/git/log", params={"limit": str(limit)})
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def git_rollback(self, sha: str) -> dict[str, Any]:
        r = await self._client.post("/git/rollback", json={"sha": sha})
        if r.status_code == 409:
            raise ShimGitConflict("a task is running")
        if r.status_code == 404:
            raise ShimGitNotFound("unknown snapshot sha")
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def git_push(self, *, url: str, ssh_private_key: str, branch: str) -> dict[str, Any]:
        # Push can be slow on big workspaces; the shim caps it at 120s.
        r = await self._client.post(
            "/git/push",
            json={"url": url, "ssh_private_key": ssh_private_key, "branch": branch},
            timeout=180.0,
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def git_verify(self, *, url: str, ssh_private_key: str) -> dict[str, Any]:
        r = await self._client.post(
            "/git/verify",
            json={"url": url, "ssh_private_key": ssh_private_key}, timeout=60.0,
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def git_clone(
        self, *, url: str, ssh_private_key: str, branch: str
    ) -> dict[str, Any]:
        # Clone can be slow on big remotes; the shim caps it on its side.
        r = await self._client.post(
            "/git/clone",
            json={"url": url, "ssh_private_key": ssh_private_key, "branch": branch},
            timeout=180.0,
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    async def shutdown(self) -> None:
        try:
            await self._client.post("/shutdown")
        except httpx.HTTPError:
            pass

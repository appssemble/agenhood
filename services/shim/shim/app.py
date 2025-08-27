from __future__ import annotations

import asyncio
import json
import os
import shutil
import zipfile
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from agentcore import sandbox
from agentcore.drivers.base import DRIVERS
from agentcore.models import ShimTaskRequest
from agentcore.tools.paths import RESERVED_DIRS
from shim.auth import TokenAuth
from shim.git_ops import GitError, GitOps
from shim.runner import TaskRunner

_ARCHIVE_CHUNK_SIZE_BYTES = 64 * 1024
_TASK_HISTORY_LIMIT = 100
_DEFAULT_GIT_LOG_LIMIT = 200


class _ZipSink:
    """Write-only, non-seekable sink so ``zipfile`` streams entries with data
    descriptors (it can't seek back to patch local headers). ``drain`` returns
    and clears the bytes buffered since the last call — yielded to the client."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0

    def write(self, data: bytes) -> int:
        self._buf += data
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        chunk = bytes(self._buf)
        self._buf.clear()
        return chunk


def _stream_workspace_zip(workspace: str) -> Iterator[bytes]:
    """Yield a zip of ``workspace`` in bounded memory: regular files only,
    excluding ``.agent-runtime``, ``.agent-state`` and ``.git``; symlinks/special files skipped;
    files that vanish mid-walk are skipped (best-effort). Reads each source file
    in 64 KiB chunks and drains the zip sink after every write, so memory stays
    constant regardless of file or workspace size."""
    ws = os.path.realpath(workspace)
    sink = _ZipSink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ws):
            dirnames[:] = [
                d for d in dirnames
                if d not in (*RESERVED_DIRS, ".git")
            ]
            for name in sorted(filenames):
                # Excluding the dirs above only prunes os.walk's directory list;
                # a *regular file* named .git (a submodule/worktree gitlink whose
                # body is a ``gitdir:`` pointer) or .agent-runtime lands in
                # filenames, so skip those by name too — git internals/secrets
                # must never enter the archive.
                if name in (*RESERVED_DIRS, ".git"):
                    continue
                full = os.path.join(dirpath, name)
                # Regular files only — skip symlinks (escape/loops) + specials.
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                arcname = os.path.relpath(full, ws)
                try:
                    with open(full, "rb") as src, zf.open(arcname, "w") as entry:
                        while True:
                            chunk = src.read(_ARCHIVE_CHUNK_SIZE_BYTES)
                            if not chunk:
                                break
                            entry.write(chunk)
                            out = sink.drain()
                            if out:
                                yield out
                except OSError:
                    continue
                out = sink.drain()  # the entry's data descriptor
                if out:
                    yield out
    yield sink.drain()  # central directory


def create_app(
    *,
    workspace: str,
    token: str,
    drivers: dict[str, Any] | None = None,
    max_workers: int = 4,
) -> FastAPI:
    app = FastAPI()
    auth = TokenAuth(token=token)
    registry = drivers if drivers is not None else DRIVERS
    max_worker_limit = max_workers

    runners: dict[str, TaskRunner] = {}
    order: list[str] = []
    # task_id -> list of asyncio.Queue for live SSE subscribers
    subscribers: dict[str, list[asyncio.Queue[Any]]] = {}
    bg_tasks: set[asyncio.Task[None]] = set()
    git = GitOps(workspace)

    async def _post_task_git(runner: TaskRunner) -> None:
        """Auto-commit (and auto-push) after every terminal task.

        Never raises: a git failure must not change the task's outcome
        (workspace git rollback spec). Results surface as 'git' events, which
        the control plane ingests like any other task event.
        """
        req = runner.request
        if not req.git_snapshots:
            return
        try:
            try:
                sha = await git.commit_all(f"task {req.task_id}: {runner.status}")
                await runner._emit("git", {"op": "commit", "ok": True, "sha": sha})
            except GitError as e:
                await runner._emit("git", {"op": "commit", "ok": False,
                                           "error": e.code})
            if req.git_push is None:
                return
            try:
                pushed = await git.push(
                    url=req.git_push.url,
                    ssh_private_key=req.git_push.ssh_private_key,
                    branch=req.git_push.branch,
                )
                await runner._emit("git", {"op": "push", "ok": True, "sha": pushed})
            except GitError as e:
                await runner._emit("git", {"op": "push", "ok": False,
                                           "error": e.code})
        except Exception:  # noqa: BLE001 — git is strictly best-effort post-task
            pass

    async def on_event(task_id: str, event: Any) -> None:
        payload = {
            "task_id": task_id,
            "seq": event.seq,
            "type": event.type,
            "ts": event.ts.isoformat(),
            "payload": event.payload,
        }
        for q in list(subscribers.get(task_id, [])):
            await q.put(payload)

    def _status_response(runner: TaskRunner) -> dict[str, Any]:
        # Field-identical to TaskRunner._status_dict(); delegate so the status
        # shape is defined in exactly one place.
        return runner._status_dict()

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        return {"ready": True, "active": len([r for r in runners.values()
                                              if r.status == "running"])}

    @app.post("/tasks", response_model=None)
    async def post_task(
        req: Request, authorization: str | None = Header(default=None)
    ) -> Response | dict[str, Any]:
        auth.check(authorization)
        try:
            body = await req.json()
            shim_req = ShimTaskRequest.model_validate(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        active = len([r for r in runners.values() if r.status == "running"])
        if active >= max_worker_limit:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "too_many_tasks",
                                   "message": "at max_workers"}},
            )
        runner = TaskRunner(
            request=shim_req, workspace=workspace,
            drivers=registry, on_event=on_event,
        )
        runners[shim_req.task_id] = runner
        order.append(shim_req.task_id)

        async def _run_and_close() -> None:
            try:
                # Baseline snapshot must exist BEFORE the task mutates the
                # workspace, or its changes get absorbed into the lazy
                # "initial snapshot" instead of the task's own commit.
                # Best-effort: a git failure must never block a task.
                try:
                    if shim_req.git_snapshots:
                        await git.ensure_repo()
                except Exception:  # noqa: BLE001
                    pass
                await runner.run()
                await _post_task_git(runner)
            finally:
                for q in list(subscribers.get(shim_req.task_id, [])):
                    await q.put(None)  # sentinel: stream end

        bg = asyncio.create_task(_run_and_close())
        bg_tasks.add(bg)
        bg.add_done_callback(bg_tasks.discard)
        return {"task_id": shim_req.task_id, "status": "running",
                "started_at": runner.started_at}

    @app.get("/tasks/{task_id}")
    async def get_task(
        task_id: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth.check(authorization)
        runner = runners.get(task_id)
        if runner is None:
            raise HTTPException(status_code=404, detail="task not found")
        return _status_response(runner)

    @app.get("/tasks")
    async def list_tasks(
        status: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth.check(authorization)
        out = []
        for tid in order[-_TASK_HISTORY_LIMIT:]:
            r = runners[tid]
            if status and r.status != status:
                continue
            out.append(_status_response(r))
        return {"tasks": out}

    @app.post("/tasks/{task_id}/cancel")
    async def cancel_task(
        task_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth.check(authorization)
        runner = runners.get(task_id)
        if runner is None:
            raise HTTPException(status_code=404, detail="task not found")
        runner.request_cancel()
        return _status_response(runner)

    @app.get("/tasks/{task_id}/events")
    async def events(
        task_id: str,
        after_seq: int = Query(default=0),
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        auth.check(authorization)
        runner = runners.get(task_id)
        if runner is None:
            raise HTTPException(status_code=404, detail="task not found")

        queue: asyncio.Queue[Any] = asyncio.Queue()
        subscribers.setdefault(task_id, []).append(queue)

        async def gen() -> Any:
            try:
                # Replay persisted events strictly after after_seq.
                replayed = 0
                for ev in runner.log.read_after(after_seq):
                    replayed = ev.seq
                    yield "data: " + json.dumps({
                        "task_id": task_id, "seq": ev.seq, "type": ev.type,
                        "ts": ev.ts.isoformat(), "payload": ev.payload,
                    }) + "\n\n"
                terminal = {"completed", "failed", "cancelled", "timed_out"}
                # If already terminal, the replay above included the final
                # status_change; close the stream.
                if runner.status in terminal:
                    return
                # Live: drain the queue until the sentinel, skipping any seq
                # already replayed (race between replay and live publish).
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    if item["seq"] <= replayed:
                        continue
                    yield "data: " + json.dumps(item) + "\n\n"
            finally:
                subs = subscribers.get(task_id, [])
                if queue in subs:
                    subs.remove(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/shutdown")
    async def shutdown(
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        auth.check(authorization)
        for r in runners.values():
            if r.status == "running":
                r.request_cancel()
        return {"shutting_down": True}

    # ---- File-management endpoints (proxied by the control plane) -----------

    def _list_workspace(prefix: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ws = os.path.realpath(workspace)
        for dirpath, dirnames, filenames in os.walk(ws):
            for reserved in RESERVED_DIRS:
                if reserved in dirnames:
                    dirnames.remove(reserved)
            # The workspace is a git repo (workspace git rollback spec); its
            # internals would drown the file browser in thousands of entries.
            if ".git" in dirnames:
                dirnames.remove(".git")
            # Emit directories too (so empty/structural folders show in the
            # browser); pruning above keeps reserved dirs out of both lists.
            for name in dirnames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ws)
                if prefix and not rel.startswith(prefix):
                    continue
                out.append({"path": rel, "size": 0, "is_dir": True})
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ws)
                if prefix and not rel.startswith(prefix):
                    continue
                out.append({"path": rel, "size": os.path.getsize(full), "is_dir": False})
        return out

    def _reject_reserved(target: str, ws: str) -> None:
        rel = os.path.relpath(target, ws)
        first = rel.split(os.sep, 1)[0]
        if first in RESERVED_DIRS:
            raise HTTPException(status_code=400, detail="reserved path not allowed")

    def _resolve_target(path: str) -> tuple[str, str]:
        """Resolve ``path`` under the workspace and enforce the shared guards:
        realpath, escape-check (must stay inside the workspace — a bare
        ``startswith`` prefix wrongly admits siblings like ``/workspace-evil``),
        and reserved-name rejection. Returns ``(ws, target)``."""
        ws = os.path.realpath(workspace)
        target = os.path.realpath(os.path.join(ws, path))
        if target != ws and not target.startswith(ws + os.sep):
            raise HTTPException(status_code=400, detail="path escape not allowed")
        _reject_reserved(target, ws)
        return ws, target

    @app.get("/files")
    async def list_files_route(
        prefix: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth.check(authorization)
        return {"files": _list_workspace(prefix)}

    @app.get("/files/raw", response_model=None)
    async def download_file_route(
        path: str = Query(...),
        authorization: str | None = Header(default=None),
    ) -> Response:
        auth.check(authorization)
        _, target = _resolve_target(path)
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="file not found")
        with open(target, "rb") as fh:
            data = fh.read()
        return Response(content=data, media_type="application/octet-stream")

    @app.put("/files/raw", status_code=204, response_model=None)
    async def upload_file_route(
        req: Request,
        path: str = Query(...),
        authorization: str | None = Header(default=None),
    ) -> Response:
        auth.check(authorization)
        _, target = _resolve_target(path)
        sandbox.makedirs_agent(os.path.dirname(target))
        body = await req.body()
        with open(target, "wb") as fh:
            fh.write(body)
        sandbox.chown_to_agent(target)
        return Response(status_code=204)

    @app.delete("/files/raw", status_code=204, response_model=None)
    async def delete_file_route(
        path: str = Query(...),
        authorization: str | None = Header(default=None),
    ) -> Response:
        auth.check(authorization)
        ws, target = _resolve_target(path)
        if target == ws:
            raise HTTPException(status_code=400, detail="cannot delete workspace root")
        if os.path.isdir(target):
            shutil.rmtree(target)
            return Response(status_code=204)
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="file not found")
        os.remove(target)
        return Response(status_code=204)

    @app.get("/files/archive", response_model=None)
    async def download_archive_route(
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        auth.check(authorization)
        return StreamingResponse(
            _stream_workspace_zip(workspace),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="workspace.zip"'},
        )

    # ---- Git endpoints (proxied by the control plane) ------------------------

    @app.get("/git/status")
    async def git_status_route(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth.check(authorization)
        return await git.repo_status()

    @app.get("/git/log")
    async def git_log_route(
        limit: int = Query(default=_DEFAULT_GIT_LOG_LIMIT),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth.check(authorization)
        return {"snapshots": await git.log_entries(limit)}

    @app.post("/git/rollback")
    async def git_rollback_route(
        req: Request, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth.check(authorization)
        body = await req.json()
        if any(r.status == "running" for r in runners.values()):
            raise HTTPException(status_code=409, detail="a task is running")
        try:
            new_sha = await git.rollback(str(body.get("sha", "")))
        except GitError as e:
            if e.code == "unknown_sha":
                raise HTTPException(status_code=404, detail="unknown sha") from None
            raise HTTPException(status_code=500, detail=e.code) from None
        return {"sha": new_sha}

    @app.post("/git/push")
    async def git_push_route(
        req: Request, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth.check(authorization)
        body = await req.json()
        try:
            sha = await git.push(
                url=str(body["url"]), ssh_private_key=str(body["ssh_private_key"]),
                branch=str(body.get("branch", "main")),
            )
        except GitError as e:
            return {"ok": False, "error_code": e.code, "error_message": str(e)}
        return {"ok": True, "sha": sha}

    @app.post("/git/verify")
    async def git_verify_route(
        req: Request, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        auth.check(authorization)
        body = await req.json()
        try:
            res = await git.verify_remote(
                url=str(body["url"]), ssh_private_key=str(body["ssh_private_key"]),
            )
        except GitError as e:
            return {"ok": False, "error_code": e.code, "error_message": str(e)}
        return {"ok": True, **res}

    @app.post("/git/clone", response_model=None)
    async def git_clone_route(
        req: Request, authorization: str | None = Header(default=None)
    ) -> Response | dict[str, Any]:
        auth.check(authorization)
        body = await req.json()
        try:
            sha = await git.clone(
                url=str(body.get("url", "")),
                ssh_private_key=str(body.get("ssh_private_key", "")),
                branch=str(body.get("branch", "main")),
            )
        except GitError as e:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": e.code, "message": str(e)}},
            )
        return {"sha": sha}

    return app

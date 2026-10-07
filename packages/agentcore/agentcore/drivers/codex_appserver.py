"""JSON-RPC client for one ``codex app-server`` process.

codex app-server speaks JSON-RPC over stdio, one JSON object per line. The
client matches replies to its requests and queues everything else for the
caller as ``{"method": ..., "params": ...}`` dicts, plus three of its own:

- ``_stderr`` ``{"line"}`` for each stderr line;
- ``_declined`` ``{"request"}`` when codex asked the client something (an
  approval, user input). The client answers with an error so a turn never
  waits on a reply;
- ``_exit`` ``{"returncode"}`` once, after the process ends.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agentcore import sandbox

CLIENT_INFO = {"name": "agenhood", "version": "1"}
_DECLINE = {"code": -32601, "message": "client requests are not supported"}


class AppServerError(Exception):
    """An error reply, a missing reply, or the process ending first."""


class AppServerClient:
    def __init__(self, proc: Any) -> None:
        self._proc = proc
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stderr_done = asyncio.Event()
        self._readers = [
            asyncio.create_task(self._read_stderr()),
            asyncio.create_task(self._read_stdout()),
        ]

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None

    async def request(
        self, method: str, params: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._send({"id": request_id, "method": method, "params": params})
        try:
            reply = await asyncio.wait_for(future, timeout)
        except TimeoutError:
            self._pending.pop(request_id, None)
            raise AppServerError(f"{method}: no reply in {timeout} s") from None
        if "error" in reply:
            error = reply["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise AppServerError(f"{method}: {message}")
        return reply.get("result") or {}

    def notify(self, method: str) -> None:
        self._send({"method": method})

    async def next_message(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._messages.get(), timeout)
        except TimeoutError:
            return None

    def terminate(self) -> None:
        sandbox.terminate(self._proc)

    def abort(self) -> None:
        """Stop without waiting: codex exits when stdin closes; SIGTERM backs it up."""
        stdin = self._proc.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
        self.terminate()

    async def close(self, timeout: float = 5.0) -> None:
        stdin = self._proc.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout)
        except TimeoutError:
            self.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 1.0)
            except TimeoutError:
                pass
        for reader in self._readers:
            if not reader.done():
                reader.cancel()
        await asyncio.gather(*self._readers, return_exceptions=True)

    def _send(self, msg: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        if stdin is None or stdin.is_closing():
            raise AppServerError("codex app-server stdin is closed")
        try:
            stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise AppServerError(f"codex app-server is gone: {exc}") from exc

    def _dispatch(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            line = raw.decode("utf-8", "replace").rstrip("\n")
            self._messages.put_nowait({"method": "_stderr", "params": {"line": line}})
            return
        if "id" in msg and ("result" in msg or "error" in msg):
            future = self._pending.pop(msg["id"], None)
            if future is not None and not future.done():
                future.set_result(msg)
        elif "id" in msg:
            try:
                self._send({"id": msg["id"], "error": _DECLINE})
            except AppServerError:
                pass
            self._messages.put_nowait(
                {"method": "_declined", "params": {"request": msg.get("method")}}
            )
        elif "method" in msg:
            self._messages.put_nowait(msg)

    async def _read_stdout(self) -> None:
        assert self._proc.stdout is not None
        try:
            while raw := await self._proc.stdout.readline():
                self._dispatch(raw)
        except Exception:  # noqa: BLE001 - a broken stream ends the session like an exit
            self.terminate()
        try:
            await asyncio.wait_for(self._stderr_done.wait(), 1.0)
        except TimeoutError:
            pass
        returncode = await self._proc.wait()
        for future in self._pending.values():
            if not future.done():
                future.set_result({"error": {"message": f"codex app-server exited {returncode}"}})
        self._pending.clear()
        self._messages.put_nowait({"method": "_exit", "params": {"returncode": returncode}})

    async def _read_stderr(self) -> None:
        try:
            if self._proc.stderr is not None:
                while raw := await self._proc.stderr.readline():
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if line:
                        self._messages.put_nowait({"method": "_stderr", "params": {"line": line}})
        except Exception:  # noqa: BLE001 - stderr is informational
            pass
        finally:
            self._stderr_done.set()


async def start_app_server(
    cmd: list[str], *, cwd: str, env: dict[str, str]
) -> AppServerClient:
    """Spawn ``codex app-server`` as the agent user and do the handshake.

    Raises FileNotFoundError when the binary is missing, AppServerError when the
    handshake fails (the process is stopped first).
    """
    proc = await sandbox.spawn_untrusted(
        cmd,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    client = AppServerClient(proc)
    try:
        await client.request("initialize", {"clientInfo": CLIENT_INFO}, timeout=30.0)
        client.notify("initialized")
    except BaseException:
        client.abort()
        raise
    return client

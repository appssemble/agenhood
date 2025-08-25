"""Async wrapper over a docker-py exec session for the container console.

Isolates all docker specifics so the WebSocket route can be unit-tested with a
fake. TTY mode is used, so exec output is a raw byte stream (no stdout/stderr
multiplexing header).
"""
from __future__ import annotations

import asyncio
from typing import Any

# Allowed login shells, tried in order. bash first; sh is the POSIX fallback
# present in essentially every image (including Alpine via the busybox shim).
_ALLOWED_SHELLS = ("/bin/bash", "/bin/sh")
DEFAULT_SHELL = "/bin/bash"
FALLBACK_SHELL = "/bin/sh"


def build_exec_cmd(*, shell: str) -> list[str]:
    """Return the exec command for *shell*, rejecting anything not allow-listed."""
    if shell not in _ALLOWED_SHELLS:
        raise ValueError(f"shell not allowed: {shell!r}")
    return [shell]


class ConsoleExec:
    """A live docker exec session bridged to async recv/send/resize/close.

    The underlying docker-py socket is blocking; we set it non-blocking and drive
    it via the event loop's socket helpers.
    """

    def __init__(self, *, api: Any, exec_id: str, raw_sock: Any) -> None:
        self._api = api
        self._exec_id = exec_id
        self._sock = raw_sock
        self._sock.setblocking(False)
        self._closed = False

    async def recv(self, n: int = 4096) -> bytes:
        """Read up to *n* bytes of exec output; b'' means the shell exited.

        Socket errors (e.g. ConnectionResetError/OSError) propagate to the caller;
        only an empty bytes return signals clean shell exit.
        """
        return await asyncio.get_running_loop().sock_recv(self._sock, n)

    async def send(self, data: bytes) -> None:
        """Write stdin bytes to the exec session."""
        await asyncio.get_running_loop().sock_sendall(self._sock, data)

    async def resize(self, *, rows: int, cols: int) -> None:
        """Resize the exec PTY (best-effort; ignores docker errors)."""
        try:
            await asyncio.to_thread(
                self._api.exec_resize, self._exec_id, height=rows, width=cols
            )
        except Exception:  # noqa: BLE001 — resize is cosmetic; never kill the session
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.close()
        except Exception:  # noqa: BLE001
            pass


def make_console_exec(
    *,
    docker_client: Any,
    docker_name: str,
    user: str = "root",
    shell: str = DEFAULT_SHELL,
) -> ConsoleExec:
    """Create + start a docker exec, returning a ConsoleExec.

    Falls back from bash to sh if the requested shell cannot be created (image
    without bash). Raises if neither shell is available.
    """
    api = docker_client.api
    last_err: Exception | None = None
    for candidate in dict.fromkeys((shell, FALLBACK_SHELL)):
        try:
            created = api.exec_create(
                docker_name,
                cmd=build_exec_cmd(shell=candidate),
                tty=True,
                stdin=True,
                stdout=True,
                stderr=True,
                user=user,
            )
            exec_id = created["Id"]
            sock = api.exec_start(exec_id, tty=True, socket=True, detach=False)
            raw = getattr(sock, "_sock", None)  # docker-py wraps the raw socket
            if raw is None:
                raise TypeError(f"expected docker-py socket wrapper, got {type(sock)}")
            return ConsoleExec(api=api, exec_id=exec_id, raw_sock=raw)
        except Exception as err:  # noqa: BLE001
            last_err = err
            continue
    raise RuntimeError(f"could not start console exec: {last_err}")

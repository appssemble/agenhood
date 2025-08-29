from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest

from control_plane.console_exec import ConsoleExec, build_exec_cmd, make_console_exec

pytestmark = pytest.mark.unit


def test_build_exec_cmd_prefers_bash_then_falls_back_to_sh():
    # Tries bash first; if bash is missing the container, sh is the fallback.
    assert build_exec_cmd(shell="/bin/bash") == ["/bin/bash"]
    assert build_exec_cmd(shell="/bin/sh") == ["/bin/sh"]


def test_build_exec_cmd_rejects_unknown_shell():
    with pytest.raises(ValueError):
        build_exec_cmd(shell="/usr/bin/python")


def _socketpair() -> tuple[socket.socket, socket.socket]:
    a, b = socket.socketpair()
    return a, b


def test_console_exec_recv_and_send_round_trip():
    a, b = _socketpair()

    async def run() -> bytes:
        ex = ConsoleExec(api=object(), exec_id="x", raw_sock=a)
        await ex.send(b"ping")
        # b receives what a sent
        assert b.recv(4096) == b"ping"
        b.sendall(b"pong")
        out = await ex.recv(4096)
        ex.close()
        return out

    assert asyncio.run(run()) == b"pong"
    b.close()


def test_console_exec_close_is_idempotent():
    a, b = _socketpair()
    ex = ConsoleExec(api=object(), exec_id="x", raw_sock=a)
    ex.close()
    ex.close()  # must not raise
    b.close()


class _FakeApi:
    def __init__(self, *, fail_shells: tuple[str, ...] = ()) -> None:
        self.fail_shells = fail_shells
        self.created_cmds: list[list[str]] = []

    def exec_create(self, name: str, *, cmd: list[str], **kw: Any) -> dict:
        self.created_cmds.append(cmd)
        if cmd[0] in self.fail_shells:
            raise RuntimeError(f"no {cmd[0]}")
        return {"Id": "exec_1"}

    def exec_start(self, exec_id: str, **kw: Any):
        s, _peer = _socketpair()
        self._peer = _peer

        class _Wrapper:
            def __init__(self, raw): self._sock = raw

        return _Wrapper(s)


class _FakeClient:
    def __init__(self, api: _FakeApi) -> None:
        self.api = api


def test_make_console_exec_falls_back_to_sh_when_bash_missing():
    api = _FakeApi(fail_shells=("/bin/bash",))
    ex = make_console_exec(docker_client=_FakeClient(api), docker_name="c")
    assert api.created_cmds == [["/bin/bash"], ["/bin/sh"]]
    ex.close()


def test_make_console_exec_does_not_retry_same_shell_twice():
    api = _FakeApi(fail_shells=("/bin/sh",))
    with pytest.raises(RuntimeError):
        make_console_exec(docker_client=_FakeClient(api), docker_name="c", shell="/bin/sh")
    # Only one attempt because shell == fallback (deduplicated).
    assert api.created_cmds == [["/bin/sh"]]

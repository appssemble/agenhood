from __future__ import annotations

import asyncio

import pytest

from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]


@requires_docker
@pytest.mark.asyncio
async def test_console_exec_round_trip():
    import docker

    from control_plane.console_exec import make_console_exec

    client = docker.from_env()
    container = client.containers.run("alpine:3", "sleep 30", detach=True, tty=True)
    try:
        ex = make_console_exec(docker_client=client, docker_name=container.id, user="root")
        # Drive an echo and read it back from the TTY stream.
        await ex.send(b"echo READY\n")
        buf = b""
        for _ in range(50):
            buf += await asyncio.wait_for(ex.recv(4096), timeout=2)
            if b"READY" in buf:
                break
        assert b"READY" in buf
        ex.close()
    finally:
        container.remove(force=True)
        client.close()

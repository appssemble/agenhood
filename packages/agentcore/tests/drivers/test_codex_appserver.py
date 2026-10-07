import os
import sys
from pathlib import Path

import pytest

from agentcore.drivers.codex_appserver import AppServerError, start_app_server

pytestmark = pytest.mark.unit

STUB = str(Path(__file__).with_name("stub_codex_app_server.py"))


async def start(tmp_path, **env):
    return await start_app_server(
        [sys.executable, STUB], cwd=str(tmp_path), env={**os.environ, **env}
    )


async def next_named(client, method):
    while True:
        msg = await client.next_message(5.0)
        assert msg is not None, f"no {method} message"
        if msg["method"] == method:
            return msg


@pytest.mark.asyncio
async def test_request_returns_the_result(tmp_path):
    client = await start(tmp_path)
    try:
        assert await client.request("test/emit", {"messages": []}) == {"emitted": 0}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_error_reply_raises(tmp_path):
    client = await start(tmp_path)
    try:
        with pytest.raises(AppServerError, match="test/fail: nope"):
            await client.request("test/fail", {"message": "nope"})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_notifications_arrive_in_order(tmp_path):
    notes = [
        {"method": "turn/started", "params": {"n": 1}},
        {"method": "turn/completed", "params": {"n": 2}},
    ]
    client = await start(tmp_path)
    try:
        await client.request("test/emit", {"messages": notes})
        assert await client.next_message(5.0) == notes[0]
        assert await client.next_message(5.0) == notes[1]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_server_requests_are_declined(tmp_path):
    client = await start(tmp_path)
    try:
        await client.request("test/ask", {})
        declined = await next_named(client, "_declined")
        assert declined["params"] == {"request": "item/commandExecution/requestApproval"}
        reply = await next_named(client, "test/reply")
        assert reply["params"]["id"] == "srv-1"
        assert reply["params"]["error"]["code"] == -32601
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stderr_lines_are_queued(tmp_path):
    client = await start(tmp_path)
    try:
        await client.request("test/stderr", {"line": "warn: something"})
        assert (await next_named(client, "_stderr"))["params"] == {"line": "warn: something"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exit_fails_the_pending_request_and_reports_the_returncode(tmp_path):
    client = await start(tmp_path)
    with pytest.raises(AppServerError, match="exited 3"):
        await client.request("test/exit", {"code": 3})
    assert (await next_named(client, "_exit"))["params"] == {"returncode": 3}
    assert client.alive is False
    await client.close()


@pytest.mark.asyncio
async def test_request_timeout_raises(tmp_path):
    client = await start(tmp_path)
    try:
        with pytest.raises(AppServerError, match="no reply"):
            await client.request("test/silent", {}, timeout=0.2)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_stops_the_process(tmp_path):
    client = await start(tmp_path)
    await client.close()
    assert client.alive is False


@pytest.mark.asyncio
async def test_abort_stops_the_process_without_waiting(tmp_path):
    client = await start(tmp_path)
    client.abort()
    await next_named(client, "_exit")
    assert client.alive is False


@pytest.mark.asyncio
async def test_missing_binary_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        await start_app_server(
            ["/nonexistent/codex", "app-server"], cwd=str(tmp_path), env=dict(os.environ)
        )


@pytest.mark.asyncio
async def test_failed_handshake_raises(tmp_path):
    with pytest.raises(AppServerError, match="init refused"):
        await start(tmp_path, STUB_FAIL_INIT="1")


@pytest.mark.asyncio
async def test_request_after_exit_raises(tmp_path):
    client = await start(tmp_path)
    with pytest.raises(AppServerError, match="exited 3"):
        await client.request("test/exit", {"code": 3})
    await next_named(client, "_exit")
    with pytest.raises(AppServerError, match="exited 3"):
        await client.request("test/emit", {"messages": []})
    await client.close()

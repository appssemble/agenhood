import asyncio
import json

import httpx
import pytest

from agentcore.drivers.base import DriverCapabilities, DriverTemplate
from agentcore.models import TaskResult
from shim.app import create_app

pytestmark = pytest.mark.unit


class GatedDriver:
    """Emits task_started, waits on a gate, then emits the rest. Lets a test
    subscribe to events while the task is still running."""
    name = "vanilla"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("vanilla", "p", [], True, True)

    def __init__(self) -> None:
        self.gate = asyncio.Event()

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", **_kwargs: object):
        await emit("task_started", {"driver": "vanilla", "model": config.model})
        await self.gate.wait()
        await emit("iteration_started", {"iteration": 1})
        await emit("status_change", {"from": "running", "to": "completed",
                                     "result": None, "error": None})
        return TaskResult(success=True, output=None)


def payload():
    return {
        "task_id": "tsk_live",
        "task": {"prompt": "hi", "output": {"type": "text"}},
        "config": {"driver": "vanilla", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk",
    }


@pytest.mark.asyncio
async def test_live_stream_orders_events(tmp_path):
    driver = GatedDriver()
    app = create_app(workspace=str(tmp_path), token="",
                     drivers={"vanilla": driver})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://shim") as c:
        await c.post("/tasks", json=payload())
        # Give the background task a moment to emit task_started.
        await asyncio.sleep(0.05)

        collected = []

        async def consume():
            async with c.stream("GET", "/tasks/tsk_live/events") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        obj = json.loads(line[len("data: "):])
                        collected.append(obj["type"])
                        if obj["type"] == "status_change":
                            return

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        driver.gate.set()  # release the rest of the events
        await asyncio.wait_for(consumer, timeout=5)

    assert collected[0] == "task_started"
    assert collected[-1] == "status_change"
    assert "iteration_started" in collected

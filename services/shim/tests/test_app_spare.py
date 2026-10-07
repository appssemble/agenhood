import asyncio

import httpx
import pytest

from agentcore.drivers.base import DriverCapabilities, DriverTemplate
from agentcore.models import TaskResult
from shim.app import create_app

pytestmark = pytest.mark.unit


class SpareAwareDriver:
    name = "vanilla"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("vanilla", "p", [], True, True)

    def __init__(self, gate=None):
        self.check = None
        self.refills = []
        self.closed = False
        self.gate = gate

    def set_capacity_check(self, check):
        self.check = check

    def refill_spare(self):
        self.refills.append(self.check())

    async def close_spare(self):
        self.closed = True

    async def run(self, *, task, config, limits, credential, emit, cancel, **_kwargs):
        if self.gate is not None:
            await self.gate.wait()
        await emit("status_change", {"from": "running", "to": "completed",
                                     "result": {"ok": True}, "error": None})
        return TaskResult(success=True, output={"ok": True})


def payload(task_id="tsk_1"):
    return {
        "task_id": task_id,
        "task": {"prompt": "hi", "output": {"type": "text"}},
        "config": {"driver": "vanilla", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk",
    }


def client_for(tmp_path, driver, max_workers=4):
    app = create_app(workspace=str(tmp_path), token="", drivers={"vanilla": driver},
                     max_workers=max_workers)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shim")


async def wait_done(c, task_id):
    for _ in range(100):
        if (await c.get(f"/tasks/{task_id}")).json()["status"] != "running":
            return
        await asyncio.sleep(0.02)
    raise AssertionError("task never finished")


@pytest.mark.asyncio
async def test_capacity_check_is_wired_at_startup(tmp_path):
    driver = SpareAwareDriver()
    async with client_for(tmp_path, driver):
        assert driver.check is not None
        assert driver.check() is True


@pytest.mark.asyncio
async def test_spare_is_refilled_after_each_task(tmp_path):
    driver = SpareAwareDriver()
    async with client_for(tmp_path, driver) as c:
        await c.post("/tasks", json=payload())
        await wait_done(c, "tsk_1")
        await asyncio.sleep(0.05)
        assert driver.refills == [True]


@pytest.mark.asyncio
async def test_no_capacity_while_every_slot_is_busy(tmp_path):
    gate = asyncio.Event()
    driver = SpareAwareDriver(gate)
    async with client_for(tmp_path, driver, max_workers=1) as c:
        await c.post("/tasks", json=payload())
        await asyncio.sleep(0.05)
        assert driver.check() is False
        gate.set()
        await wait_done(c, "tsk_1")
        assert driver.check() is True


@pytest.mark.asyncio
async def test_shutdown_closes_the_spare(tmp_path):
    driver = SpareAwareDriver()
    async with client_for(tmp_path, driver) as c:
        assert (await c.post("/shutdown")).status_code == 200
        assert driver.closed


@pytest.mark.asyncio
async def test_failing_refill_does_not_break_the_task(tmp_path):
    driver = SpareAwareDriver()

    def boom():
        raise RuntimeError("refill failed")

    driver.refill_spare = boom
    async with client_for(tmp_path, driver) as c:
        await c.post("/tasks", json=payload())
        await wait_done(c, "tsk_1")
        assert (await c.get("/tasks/tsk_1")).json()["status"] == "completed"


@pytest.mark.asyncio
async def test_refill_sees_capacity_with_a_single_worker(tmp_path):
    driver = SpareAwareDriver()
    async with client_for(tmp_path, driver, max_workers=1) as c:
        await c.post("/tasks", json=payload())
        await wait_done(c, "tsk_1")
        await asyncio.sleep(0.05)
        assert driver.refills == [True]


@pytest.mark.asyncio
async def test_shutdown_survives_a_failing_close_spare(tmp_path):
    bad = SpareAwareDriver()
    good = SpareAwareDriver()

    async def boom():
        raise RuntimeError("close failed")

    bad.close_spare = boom
    app = create_app(workspace=str(tmp_path), token="",
                     drivers={"bad": bad, "good": good})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://shim") as c:
        assert (await c.post("/shutdown")).status_code == 200
    assert good.closed

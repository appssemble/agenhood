import pytest

from agentcore.drivers.base import DriverCapabilities, DriverTemplate
from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimTaskRequest,
    TaskBody,
    TaskResult,
)
from shim.runner import TaskRunner

pytestmark = pytest.mark.unit


class FakeDriver:
    name = "fake"
    capabilities = DriverCapabilities(True, True, True, None)
    default_template = DriverTemplate("fake", "p", [], True, True)

    def __init__(self, script):
        self._script = script

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", **_kwargs: object):
        for event_type, payload in self._script:
            await emit(event_type, payload)
        return TaskResult(success=True, output={"ok": True})


def make_request():
    return ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="fake", model="m"),
        limits=ResolvedLimits(max_iterations=5, max_tokens=1000, timeout_seconds=30),
        llm_credential="sk-secret",
    )


@pytest.mark.asyncio
async def test_runner_runs_driver_and_persists_events(tmp_path):
    driver = FakeDriver([
        ("task_started", {"driver": "fake", "model": "m"}),
        ("status_change", {"from": "running", "to": "completed",
                           "result": {"ok": True}, "error": None}),
    ])
    runner = TaskRunner(
        request=make_request(), workspace=str(tmp_path),
        drivers={"fake": driver}, on_event=None,
    )
    await runner.run()
    events = runner.log.read_all()
    assert events[0].type == "task_started"
    assert events[-1].type == "status_change"
    assert runner.status == "completed"
    assert runner.result == {"ok": True}


@pytest.mark.asyncio
async def test_runner_unknown_driver_fails(tmp_path):
    req = make_request()
    runner = TaskRunner(request=req, workspace=str(tmp_path),
                        drivers={}, on_event=None)
    await runner.run()
    assert runner.status == "failed"
    assert runner.error["code"] == "validation_error"
    # a terminal status_change event was still written
    assert runner.log.read_all()[-1].type == "status_change"


@pytest.mark.asyncio
async def test_runner_seq_assigned_by_eventlog(tmp_path):
    driver = FakeDriver([
        ("task_started", {"driver": "fake", "model": "m"}),
        ("iteration_started", {"iteration": 1}),
        ("status_change", {"from": "running", "to": "completed",
                           "result": None, "error": None}),
    ])
    runner = TaskRunner(request=make_request(), workspace=str(tmp_path),
                        drivers={"fake": driver}, on_event=None)
    await runner.run()
    seqs = [e.seq for e in runner.log.read_all()]
    assert seqs == [1, 2, 3]


@pytest.mark.asyncio
async def test_runner_streams_to_live_subscriber(tmp_path):
    received = []

    async def on_event(task_id, event):
        received.append((task_id, event.type))

    driver = FakeDriver([
        ("task_started", {"driver": "fake", "model": "m"}),
        ("status_change", {"from": "running", "to": "completed",
                           "result": None, "error": None}),
    ])
    runner = TaskRunner(request=make_request(), workspace=str(tmp_path),
                        drivers={"fake": driver}, on_event=on_event)
    await runner.run()
    assert ("tsk_1", "task_started") in received


@pytest.mark.asyncio
async def test_runner_credential_never_in_events(tmp_path):
    driver = FakeDriver([
        ("task_started", {"driver": "fake", "model": "m"}),
        ("status_change", {"from": "running", "to": "completed",
                           "result": None, "error": None}),
    ])
    runner = TaskRunner(request=make_request(), workspace=str(tmp_path),
                        drivers={"fake": driver}, on_event=None)
    await runner.run()
    raw = (tmp_path / ".agent-runtime" / "events" / "tsk_1.jsonl").read_text()
    assert "sk-secret" not in raw

from __future__ import annotations

import asyncio

import pytest

from agentcore.models import ShimSkill, ShimTaskRequest, TaskResult
from shim.runner import TaskRunner

pytestmark = pytest.mark.unit


class CapturingDriver:
    name = "opencode"

    def __init__(self) -> None:
        self.seen_skills = None

    async def run(self, *, task, config, limits, credential, emit, cancel,
                  workspace="/workspace", skills=None, **_kwargs):
        self.seen_skills = skills
        await emit("status_change", {"from": "running", "to": "completed",
                                     "result": "ok", "error": None})
        return TaskResult(success=True, output="ok")


@pytest.mark.asyncio
async def test_runner_forwards_skills_to_driver(tmp_path):
    driver = CapturingDriver()
    req = ShimTaskRequest.model_validate({
        "task_id": "tsk_1",
        "task": {"prompt": "hi"},
        "config": {"driver": "opencode", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 100, "timeout_seconds": 30},
        "llm_credential": "sk",
        "skills": [{"name": "git-release", "description": "d", "body": "b"}],
    })
    runner = TaskRunner(request=req, workspace=str(tmp_path),
                        drivers={"opencode": driver}, on_event=None)
    await runner.run()
    assert driver.seen_skills == [ShimSkill(name="git-release", description="d", body="b")]

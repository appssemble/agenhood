import pytest

from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimTaskRequest,
    TaskBody,
    TaskResult,
)
from shim.runner import TaskRunner

pytestmark = pytest.mark.unit


class _CaptureDriver:
    name = "vanilla"

    def __init__(self) -> None:
        self.kwargs = {}

    async def run(self, **kwargs):
        self.kwargs = kwargs
        return TaskResult(success=True, output="ok")


@pytest.mark.asyncio
async def test_runner_forwards_env(tmp_path) -> None:
    req = ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="m"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=10, timeout_seconds=5),
        llm_credential="",
        env={"MY_VAR": "x"},
    )
    driver = _CaptureDriver()
    runner = TaskRunner(
        request=req, workspace=str(tmp_path), drivers={"vanilla": driver}
    )
    await runner.run()
    assert driver.kwargs["env"] == {"MY_VAR": "x"}

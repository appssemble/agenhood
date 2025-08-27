from __future__ import annotations

import pytest

from agentcore.models import (
    AgentConfig,
    ResolvedLimits,
    ShimTaskRequest,
    TaskBody,
    TaskResult,
)
from shim.runner import TaskRunner


class _CaptureDriver:
    name = "vanilla"

    def __init__(self) -> None:
        self.seen: dict = {}

    async def run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.seen = kwargs
        return TaskResult(success=True, output="ok")


@pytest.mark.asyncio
async def test_runner_threads_credential_kind_and_meta(tmp_path) -> None:
    drv = _CaptureDriver()
    req = ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="gpt-5.1-codex"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=10, timeout_seconds=60),
        llm_credential="acc-token",
        credential_kind="oauth_subscription",
        credential_meta={"account_id": "acct_1", "expires_ms": 123},
    )
    runner = TaskRunner(request=req, workspace=str(tmp_path), drivers={"vanilla": drv})
    await runner.run()
    assert drv.seen["credential"] == "acc-token"
    assert drv.seen["credential_kind"] == "oauth_subscription"
    assert drv.seen["credential_meta"] == {"account_id": "acct_1", "expires_ms": 123}


def test_shim_request_defaults_to_api_key() -> None:
    req = ShimTaskRequest(
        task_id="t",
        task=TaskBody(prompt="x"),
        config=AgentConfig(driver="vanilla", model="claude-opus-4-7"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=10, timeout_seconds=60),
        llm_credential="k",
    )
    assert req.credential_kind == "api_key"
    assert req.credential_meta == {}

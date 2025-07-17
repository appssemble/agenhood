import asyncio

import pytest

from agentcore.drivers.base import (
    DRIVERS,
    DriverCapabilities,
    DriverTemplate,
    get_driver,
    register,
)
from agentcore.errors import NotFoundError
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody, TaskResult


class _FakeDriver:
    name = "fake"
    capabilities = DriverCapabilities(
        supports_tools=True,
        supports_structured_output=True,
        supports_cancel=True,
    )
    default_template = DriverTemplate(
        driver="fake",
        default_system_prompt="You are fake.",
        available_tools=["read_file"],
        tools_user_editable=True,
        supports_context=True,
    )

    async def run(
        self,
        *,
        task: TaskBody,
        config: AgentConfig,
        limits: ResolvedLimits,
        credential: str,
        emit,
        cancel,
        workspace: str = "/workspace",
        **_kwargs: object,
    ) -> TaskResult:
        await emit("task_started", {"driver": self.name, "model": config.model})
        return TaskResult(success=True, output=task.prompt.upper())


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(DRIVERS)
    DRIVERS.clear()
    yield
    DRIVERS.clear()
    DRIVERS.update(saved)


def test_register_then_lookup():
    driver = _FakeDriver()
    register(driver)
    assert get_driver("fake") is driver
    assert "fake" in DRIVERS


def test_get_unknown_driver_raises_not_found_with_field():
    err_cls = NotFoundError
    with pytest.raises(err_cls) as exc:
        get_driver("does_not_exist")
    assert exc.value.code == "not_found"
    assert exc.value.field == "driver"


def test_registered_fake_driver_runs_via_protocol():
    register(_FakeDriver())
    seen: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        seen.append((event_type, payload))

    async def go() -> TaskResult:
        return await get_driver("fake").run(
            task=TaskBody(prompt="hello"),
            config=AgentConfig(driver="fake", model="claude-opus-4-7"),
            limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
            credential="cred",
            emit=emit,
            cancel=asyncio.Event(),
        )

    result = asyncio.run(go())
    assert result.success is True
    assert result.output == "HELLO"
    assert seen == [("task_started", {"driver": "fake", "model": "claude-opus-4-7"})]

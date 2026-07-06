import pytest

from agentcore.models import AgentConfig
from control_plane.schemas import (
    ConfigPatch,
    CreateContainerRequest,
    TaskSubmitResponse,
)

pytestmark = pytest.mark.unit


def test_create_container_defaults() -> None:
    req = CreateContainerRequest(name="c1")
    assert req.template_id is None
    assert req.config is None
    assert req.metadata == {}
    assert req.image_variant == "full"


def test_create_container_with_inline_config() -> None:
    req = CreateContainerRequest(
        name="c1",
        config=AgentConfig(driver="vanilla", model="claude-opus-4-7"),
    )
    assert req.config is not None
    assert req.config.driver == "vanilla"


def test_config_patch_is_full_agent_config() -> None:
    patch = ConfigPatch(driver="vanilla", model="claude-opus-4-7", tools=["read_file"])
    assert patch.tools == ["read_file"]
    assert patch.system_prompt_mode == "augment"


def test_task_submit_response_shape() -> None:
    out = TaskSubmitResponse(
        task_id="tsk_x", status="running", started_at="2026-05-20T00:00:00Z"
    )
    assert out.model_dump() == {
        "task_id": "tsk_x",
        "status": "running",
        "started_at": "2026-05-20T00:00:00Z",
        "credential_used": None,
        "session_id": None,
    }


def test_usage_response_serializes_from_alias() -> None:
    from control_plane.schemas import UsageBucketOut, UsageResponse

    resp = UsageResponse(
        from_="2026-05-27T00:00:00+00:00",
        to="2026-06-03T00:00:00+00:00",
        interval="day",
        series=[UsageBucketOut(start="2026-05-27T00:00:00+00:00",
                               tokens_in=5, tokens_out=2, tasks=1, iterations=3)],
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped["from"] == "2026-05-27T00:00:00+00:00"
    assert dumped["series"][0]["tokens_in"] == 5


def test_breakdown_response_shape() -> None:
    from control_plane.schemas import BreakdownGroupOut, BreakdownResponse

    resp = BreakdownResponse(
        from_="a", to="b", by="container",
        groups=[BreakdownGroupOut(key="ctr_1", label="support-bot",
                                  tokens_in=10, tokens_out=4, tasks=2, iterations=6)],
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped["by"] == "container"
    assert dumped["groups"][0]["label"] == "support-bot"


def test_task_out_container_name_optional_defaults_none() -> None:
    from agentcore.models import AgentConfig
    from control_plane.schemas import TaskOut

    cfg = AgentConfig(driver="vanilla", model="m", system_prompt="",
                      system_prompt_mode="augment", tools=[],
                      context={"variables": {}, "text": None, "files": []})
    t = TaskOut(task_id="t1", container_id="c1", prompt="", status="completed",
                driver="vanilla", model="m", config_snapshot=cfg,
                iterations_used=0, tokens_in=0, tokens_out=0,
                started_at=None, ended_at=None, created_at="t")
    assert t.container_name is None

import pytest

from agentcore.models import (
    AgentConfig,
    ContextSpec,
    ResolvedLimits,
    ShimTaskRequest,
    TaskBody,
)
from control_plane.snapshot import build_shim_request, snapshot_config

pytestmark = pytest.mark.unit


def _config() -> AgentConfig:
    return AgentConfig(
        driver="vanilla",
        model="claude-opus-4-7",
        system_prompt="be terse",
        system_prompt_mode="augment",
        tools=["read_file", "bash"],
        context=ContextSpec(variables={"k": "v"}, text="ctx", files=["a.md"]),
    )


def test_snapshot_copies_config_verbatim() -> None:
    cfg = _config()
    snap = snapshot_config(cfg)
    # Snapshot is a plain dict equal to the model dump (by field name).
    assert snap == cfg.model_dump()
    # Mutating the snapshot does not touch the source config.
    snap["system_prompt"] = "changed"
    assert cfg.system_prompt == "be terse"


def test_build_shim_request_carries_snapshot_limits_and_credential() -> None:
    cfg = _config()
    body = TaskBody(prompt="do it")
    limits = ResolvedLimits(max_iterations=10, max_tokens=1000, timeout_seconds=60)
    req = build_shim_request(
        task_id="tsk_1", body=body, config=cfg, limits=limits, credential="sk-test"
    )
    assert isinstance(req, ShimTaskRequest)
    assert req.task_id == "tsk_1"
    assert req.task == body
    assert req.config == cfg
    assert req.limits == limits
    assert req.llm_credential == "sk-test"


def test_credential_not_in_persisted_body() -> None:
    # The persisted task body must never contain the credential.
    body = TaskBody(prompt="do it")
    assert "credential" not in body.model_dump()
    assert "llm_credential" not in body.model_dump()

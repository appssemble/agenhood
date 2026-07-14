from __future__ import annotations

from agentcore.models import AgentConfig, ResolvedLimits, ShimTaskRequest, TaskBody


def _req(**kw) -> ShimTaskRequest:
    return ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="m"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        llm_credential="",
        **kw,
    )


def test_env_defaults_to_empty_dict() -> None:
    assert _req().env == {}


def test_env_round_trips() -> None:
    req = _req(env={"FOO": "bar"})
    assert ShimTaskRequest.model_validate(req.model_dump()).env == {"FOO": "bar"}


def test_old_shim_ignores_unknown_field_semantics() -> None:
    # Forward-compat direction: a payload WITHOUT env validates fine (old
    # control plane → new shim); pydantic's default config also ignores
    # unknown fields (new control plane → old shim).
    data = _req().model_dump()
    data.pop("env")
    assert ShimTaskRequest.model_validate(data).env == {}

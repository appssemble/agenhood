from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentcore.models import (
    AgentConfig,
    Event,
    OutputContract,
    TaskBody,
)


def test_output_contract_schema_alias_round_trips():
    # Clients send the field as `schema`; we expose it internally as `json_schema`.
    raw = {"type": "structured", "schema": {"type": "object"}}
    oc = OutputContract.model_validate(raw)
    assert oc.json_schema == {"type": "object"}
    # Dumping by alias must reproduce the wire shape clients sent.
    assert oc.model_dump(by_alias=True, exclude_none=True) == raw
    # Construction by the python name must also work (populate_by_name).
    assert OutputContract(json_schema={"a": 1}).json_schema == {"a": 1}


def test_task_body_parses_full_payload_and_defaults():
    body = TaskBody.model_validate({"prompt": "do the thing"})
    assert body.prompt == "do the thing"
    assert body.output.type == "text"
    assert body.output.json_schema is None
    assert body.limits.max_iterations is None
    assert body.metadata == {}


def test_agent_config_defaults_augment_and_empty_tools():
    cfg = AgentConfig(driver="vanilla", model="claude-opus-4-7")
    assert cfg.system_prompt_mode == "augment"
    assert cfg.tools == []
    assert cfg.system_prompt == ""
    assert cfg.context.variables == {}
    assert cfg.context.files == []


def test_event_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Event(
            seq=1,
            type="not_a_real_event",  # type: ignore[arg-type]
            ts=datetime.now(UTC),
            payload={},
        )


def test_event_accepts_known_type():
    ev = Event(
        seq=1,
        type="task_started",
        ts=datetime.now(UTC),
        payload={"driver": "vanilla", "model": "claude-opus-4-7"},
    )
    assert ev.type == "task_started"
    assert ev.seq == 1


def test_task_body_session_id_defaults_to_none():
    assert TaskBody(prompt="hi").session_id is None


def test_task_body_accepts_session_id():
    assert TaskBody(prompt="hi", session_id="sess-1").session_id == "sess-1"


def test_shim_task_request_session_fields_default():
    from agentcore.models import AgentConfig, ResolvedLimits, ShimTaskRequest

    req = ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="m"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        llm_credential="cred",
    )
    assert req.session_id is None
    assert req.session_is_continuation is False


def test_shim_task_request_accepts_session_fields():
    from agentcore.models import AgentConfig, ResolvedLimits, ShimTaskRequest

    req = ShimTaskRequest(
        task_id="tsk_1",
        task=TaskBody(prompt="hi"),
        config=AgentConfig(driver="vanilla", model="m"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        llm_credential="cred",
        session_id="sess-1",
        session_is_continuation=True,
    )
    assert req.session_id == "sess-1"
    assert req.session_is_continuation is True

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

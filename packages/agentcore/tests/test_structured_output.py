"""Shared structured-output helpers (spec: structured output across all drivers)."""
import pytest

from agentcore.structured_output import (
    MAX_ATTEMPTS,
    correction_prompt,
    native_subset_compatible,
    parse_and_validate,
    schema_instructions,
    validate_value,
)

pytestmark = pytest.mark.unit

OBJ_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}
ARR_SCHEMA = {"type": "array", "items": {"type": "string"}}


def test_max_attempts_is_three():
    assert MAX_ATTEMPTS == 3


# ---- validate_value --------------------------------------------------------

def test_validate_value_ok():
    assert validate_value({"name": "x"}, OBJ_SCHEMA) is None


def test_validate_value_error_mentions_schema():
    err = validate_value({"name": 1}, OBJ_SCHEMA)
    assert err is not None
    assert "does not match the required schema" in err


# ---- parse_and_validate ----------------------------------------------------

def test_parse_plain_object():
    parsed, err = parse_and_validate('{"name": "x"}', OBJ_SCHEMA)
    assert err is None
    assert parsed == {"name": "x"}


def test_parse_fenced_object():
    parsed, err = parse_and_validate('```json\n{"name": "x"}\n```', OBJ_SCHEMA)
    assert err is None
    assert parsed == {"name": "x"}


def test_parse_prose_wrapped_object():
    parsed, err = parse_and_validate(
        'Here is the result: {"name": "x"} — done!', OBJ_SCHEMA
    )
    assert err is None
    assert parsed == {"name": "x"}


def test_parse_top_level_array():
    parsed, err = parse_and_validate('["a", "b"]', ARR_SCHEMA)
    assert err is None
    assert parsed == ["a", "b"]


def test_parse_no_json():
    parsed, err = parse_and_validate("no json here", OBJ_SCHEMA)
    assert parsed is None
    assert err == "no JSON value found in the response"


def test_parse_invalid_json():
    parsed, err = parse_and_validate('{"name": ', OBJ_SCHEMA)
    assert parsed is None
    assert err is not None and err.startswith("invalid JSON")


def test_parse_valid_json_failing_schema():
    parsed, err = parse_and_validate('{"name": 42}', OBJ_SCHEMA)
    assert parsed is None
    assert err is not None and "does not match the required schema" in err


def test_parse_object_after_bracketed_citation():
    parsed, err = parse_and_validate('Sources: [1] {"name": "x"}', OBJ_SCHEMA)
    assert err is None
    assert parsed == {"name": "x"}


def test_parse_object_after_bracketed_log_prefix():
    parsed, err = parse_and_validate('[INFO] done. {"name": "x"}', OBJ_SCHEMA)
    assert err is None
    assert parsed == {"name": "x"}


# ---- native_subset_compatible ----------------------------------------------

def test_native_subset_accepts_strict_object():
    assert native_subset_compatible(OBJ_SCHEMA) is True


def test_native_subset_accepts_nested_strict_object():
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["user", "tags"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is True


def test_native_subset_rejects_array_root():
    assert native_subset_compatible(ARR_SCHEMA) is False


def test_native_subset_rejects_missing_additional_properties_false():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    assert native_subset_compatible(schema) is False


def test_native_subset_rejects_optional_properties():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is False


def test_native_subset_rejects_ref():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/x"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is False


def test_native_subset_rejects_numeric_constraints():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer", "minimum": 0}},
        "required": ["n"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is False


def test_native_subset_tolerates_format_annotation():
    schema = {
        "type": "object",
        "properties": {"email": {"type": "string", "format": "email"}},
        "required": ["email"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is True


def test_native_subset_rejects_type_list():
    schema = {
        "type": "object",
        "properties": {"a": {"type": ["object", "null"],
                             "properties": {"b": {"type": "string"}},
                             "required": ["b"], "additionalProperties": False}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is False


def test_native_subset_rejects_typeless_properties_node():
    schema = {
        "type": "object",
        "properties": {"a": {"properties": {"b": {"type": "string"}},
                             "required": ["b"], "additionalProperties": False}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert native_subset_compatible(schema) is False


# ---- prompt helpers --------------------------------------------------------

def test_schema_instructions_embed_schema():
    text = schema_instructions(OBJ_SCHEMA)
    assert text.startswith("## Output")
    assert '"additionalProperties"' in text


def test_correction_prompt_embeds_error():
    text = correction_prompt("invalid JSON: boom")
    assert "invalid JSON: boom" in text
    assert "ONLY" in text


# ---- run_structured_attempts ------------------------------------------------

from agentcore.models import TaskResult  # noqa: E402
from agentcore.structured_output import run_structured_attempts  # noqa: E402


def collector():
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


def scripted_attempts(outputs, latest_id, new_id="id_1"):
    """Fake run_attempt: pops the next scripted output per call, records args."""
    calls = []

    async def run_attempt(prompt, resume_id, timeout_seconds, emit_running):
        calls.append(
            {"prompt": prompt, "resume_id": resume_id,
             "timeout_seconds": timeout_seconds, "emit_running": emit_running}
        )
        latest_id["id"] = new_id
        out = outputs.pop(0)
        if isinstance(out, TaskResult):
            return out
        return TaskResult(success=True, output=out)

    return calls, run_attempt


@pytest.mark.asyncio
async def test_wrapper_valid_first_attempt():
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts(['{"name": "x"}'], latest_id)
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="do it", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )

    assert result.success is True
    assert result.output == {"name": "x"}
    assert len(calls) == 1
    # first attempt: schema instructions appended, no resume, running emitted
    assert "## Output" in calls[0]["prompt"]
    assert calls[0]["resume_id"] is None
    assert calls[0]["emit_running"] is True
    completed = [p for t, p in events if t == "status_change" and p["to"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["result"] == {"success": True, "output": {"name": "x"}}


@pytest.mark.asyncio
async def test_wrapper_object_candidate_skips_text_parse():
    # A driver may hand back an already-parsed object (claude structured_output).
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts([{"name": "x"}], latest_id)
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="p", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )
    assert result.output == {"name": "x"}


@pytest.mark.asyncio
async def test_wrapper_retries_with_correction_and_resume():
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts(["not json", '{"name": "x"}'], latest_id)
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="p", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )

    assert result.success is True
    assert len(calls) == 2
    assert "Invalid output" in calls[1]["prompt"]
    assert calls[1]["resume_id"] == "id_1"
    assert calls[1]["emit_running"] is False
    warns = [p for t, p in events
             if t == "log" and p["message"] == "structured_output_invalid"]
    assert len(warns) == 1
    assert warns[0]["data"]["attempt"] == 1


@pytest.mark.asyncio
async def test_wrapper_fails_after_max_attempts():
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts(["a", "b", "c"], latest_id)
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="p", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )

    assert result.success is False
    assert result.reason == "invalid_structured_output"
    assert len(calls) == MAX_ATTEMPTS
    failed = [p for t, p in events if t == "status_change" and p["to"] == "failed"]
    assert failed[-1]["error"]["code"] == "invalid_structured_output"


@pytest.mark.asyncio
async def test_wrapper_passes_through_attempt_failure():
    # cancel/timeout/CLI error: the attempt already emitted its terminal event.
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts(
        [TaskResult(success=False, reason="timeout")], latest_id
    )
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="p", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )
    assert result.success is False
    assert result.reason == "timeout"
    assert len(calls) == 1
    assert events == []  # wrapper emitted nothing — the attempt owns failures


@pytest.mark.asyncio
async def test_wrapper_no_resume_id_fails_without_retry():
    latest_id = {"id": None}
    calls, run_attempt = scripted_attempts(["not json"], latest_id, new_id=None)
    events, emit = collector()

    result = await run_structured_attempts(
        schema=OBJ_SCHEMA, task_prompt="p", timeout_seconds=60,
        emit=emit, latest_id=latest_id, run_attempt=run_attempt,
    )
    assert result.success is False
    assert result.reason == "invalid_structured_output"
    assert len(calls) == 1

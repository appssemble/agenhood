import pytest

from agentcore.errors import (
    ERROR_CODES,
    AgentRuntimeError,
    NotFoundError,
    ValidationError,
    error_envelope,
)


def test_error_envelope_matches_spec_shape_with_field():
    env = error_envelope("validation_error", "tools must be allowed", field="tools")
    assert env == {
        "error": {
            "code": "validation_error",
            "message": "tools must be allowed",
            "field": "tools",
        }
    }


def test_error_envelope_omits_field_when_absent():
    env = error_envelope("not_found", "no such container")
    assert env == {"error": {"code": "not_found", "message": "no such container"}}


def test_exception_carries_canonical_code_and_serializes():
    err = ValidationError("bad tool", field="tools")
    assert isinstance(err, AgentRuntimeError)
    assert err.code == "validation_error"
    assert err.field == "tools"
    assert err.to_envelope() == {
        "error": {"code": "validation_error", "message": "bad tool", "field": "tools"}
    }


def test_not_found_uses_its_code():
    assert NotFoundError("gone").code == "not_found"


def test_envelope_rejects_unknown_code():
    with pytest.raises(ValueError):
        error_envelope("nope", "x")  # type: ignore[arg-type]


def test_all_canonical_codes_present():
    assert ERROR_CODES == frozenset(
        {
            "validation_error",
            "no_credential",
            "container_not_runnable",
            "too_many_tasks",
            "running_capacity_exhausted",
            "max_containers_reached",
            "external_id_in_use",
            "too_many_requests",
            "shim_unavailable",
            "unauthorized",
            "forbidden",
            "not_found",
        }
    )

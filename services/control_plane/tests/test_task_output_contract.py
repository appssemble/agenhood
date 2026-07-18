"""Server-side guards for structured tasks (structured output across drivers)."""
import pytest

from agentcore.models import OutputContract, TaskBody
from control_plane.errors import APIError
from control_plane.routers.tasks import validate_output_contract

pytestmark = pytest.mark.unit

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}


def _body(output: OutputContract) -> TaskBody:
    return TaskBody(prompt="do the thing", output=output)


def test_text_task_passes_any_driver():
    validate_output_contract(_body(OutputContract(type="text")), "codex")


def test_structured_task_passes_supported_driver():
    body = _body(OutputContract(type="structured", schema=SCHEMA))
    # Task 6 Step 5 extends this tuple to all five drivers once the CLI
    # drivers' capability flips land (Tasks 4-6).
    for driver in ("vanilla", "api"):
        validate_output_contract(body, driver)


def test_structured_task_rejects_unknown_driver():
    body = _body(OutputContract(type="structured", schema=SCHEMA))
    with pytest.raises(APIError) as exc:
        validate_output_contract(body, "no-such-driver")
    assert exc.value.status_code == 400
    assert exc.value.code == "structured_output_unsupported"


def test_structured_task_requires_schema():
    body = _body(OutputContract(type="structured"))
    with pytest.raises(APIError) as exc:
        validate_output_contract(body, "vanilla")
    assert exc.value.code == "invalid_output_schema"


def test_structured_task_rejects_malformed_schema():
    bad = {"type": "object", "properties": {"x": {"type": "not-a-type"}}}
    body = _body(OutputContract(type="structured", schema=bad))
    with pytest.raises(APIError) as exc:
        validate_output_contract(body, "vanilla")
    assert exc.value.code == "invalid_output_schema"

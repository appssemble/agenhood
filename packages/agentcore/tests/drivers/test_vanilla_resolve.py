import pytest

from agentcore.drivers.vanilla import DONE_TOOL, resolve_output
from agentcore.models import OutputContract, TaskBody

pytestmark = pytest.mark.unit


def test_done_tool_spec_shape():
    assert DONE_TOOL.name == "done"
    props = DONE_TOOL.input_schema["properties"]
    assert "success" in props
    assert "output" in props
    assert "reason" in props


def test_resolve_failure_accepts_without_schema_check():
    task = TaskBody(
        prompt="x",
        output=OutputContract(type="structured", schema={"type": "object",
                                                          "required": ["foo"]}),
    )
    ok, payload = resolve_output(
        {"success": False, "reason": "couldn't find data"}, task, "/workspace"
    )
    assert ok
    assert payload == {"success": False, "reason": "couldn't find data"}


def test_resolve_structured_valid():
    task = TaskBody(
        prompt="x",
        output=OutputContract(
            type="structured",
            schema={"type": "object", "required": ["name"],
                    "properties": {"name": {"type": "string"}}},
        ),
    )
    ok, payload = resolve_output(
        {"success": True, "output": {"name": "listmonk"}}, task, "/workspace"
    )
    assert ok
    assert payload == {"success": True, "output": {"name": "listmonk"}}


def test_resolve_structured_invalid_returns_error_string():
    task = TaskBody(
        prompt="x",
        output=OutputContract(
            type="structured",
            schema={"type": "object", "required": ["name"],
                    "properties": {"name": {"type": "string"}}},
        ),
    )
    ok, payload = resolve_output(
        {"success": True, "output": {"wrong": 1}}, task, "/workspace"
    )
    assert not ok
    assert isinstance(payload, str)
    assert "schema" in payload.lower() or "name" in payload.lower()


def test_resolve_text_output():
    task = TaskBody(prompt="x", output=OutputContract(type="text"))
    ok, payload = resolve_output(
        {"success": True, "output": "the answer is 42"}, task, "/workspace"
    )
    assert ok
    assert payload == {"success": True, "output": "the answer is 42"}


def test_resolve_files_output_snapshots_workspace(tmp_path):
    (tmp_path / "report.md").write_text("# report")
    task = TaskBody(prompt="x", output=OutputContract(type="files"))
    ok, payload = resolve_output(
        {"success": True, "output": "done"}, task, str(tmp_path)
    )
    assert ok
    assert payload["success"] is True
    assert any(f["path"] == "report.md" for f in payload["files"])

import json
import logging

from control_plane.logging_setup import JsonFormatter


def _format(record_kwargs, extra=None):
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="control_plane", level=logging.INFO, pathname=__file__,
        lineno=1, msg=record_kwargs["msg"], args=(), exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return json.loads(formatter.format(record))


def test_emits_valid_json_with_required_keys():
    obj = _format({"msg": "task submitted"})
    assert obj["msg"] == "task submitted"
    assert obj["level"] == "info"
    assert "ts" in obj and obj["ts"].endswith("Z")


def test_includes_bound_context_fields():
    obj = _format({"msg": "x"},
                  extra={"tenant_id": "tnt_1", "container_id": "con_2",
                         "task_id": "tsk_3"})
    assert obj["tenant_id"] == "tnt_1"
    assert obj["container_id"] == "con_2"
    assert obj["task_id"] == "tsk_3"


def test_omits_unset_optional_context_fields():
    obj = _format({"msg": "x"})
    assert "tenant_id" not in obj
    assert "container_id" not in obj
    assert "task_id" not in obj


def test_level_name_lowercased():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="cp", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="warned", args=(), exc_info=None,
    )
    obj = json.loads(formatter.format(record))
    assert obj["level"] == "warning"


def test_message_with_format_args_is_rendered():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="cp", level=logging.INFO, pathname=__file__, lineno=1,
        msg="provisioned %s", args=("con_9",), exc_info=None,
    )
    obj = json.loads(formatter.format(record))
    assert obj["msg"] == "provisioned con_9"

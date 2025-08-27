import json

import pytest

from shim.eventlog import EventLog

pytestmark = pytest.mark.unit


def test_seq_monotonic_from_one(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    e1 = log.append("task_started", {"driver": "vanilla", "model": "m"})
    e2 = log.append("iteration_started", {"iteration": 1})
    assert e1.seq == 1
    assert e2.seq == 2
    assert e1.type == "task_started"


def test_read_all_returns_in_order(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    log.append("task_started", {"driver": "v", "model": "m"})
    log.append("log", {"level": "info", "message": "hi", "data": {}})
    events = log.read_all()
    assert [e.seq for e in events] == [1, 2]
    assert events[0].type == "task_started"


def test_resume_after_seq_returns_strictly_after(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    for i in range(5):
        log.append("iteration_started", {"iteration": i})
    after = log.read_after(2)
    assert [e.seq for e in after] == [3, 4, 5]


def test_persists_across_instances(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    log.append("task_started", {"driver": "v", "model": "m"})
    log.append("log", {"level": "info", "message": "x", "data": {}})
    # A fresh instance resumes the seq counter from disk.
    log2 = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    e3 = log2.append("status_change",
                     {"from": "running", "to": "completed",
                      "result": {"success": True}, "error": None})
    assert e3.seq == 3
    assert len(log2.read_all()) == 3


def test_jsonl_lines_are_valid_json(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    log.append("task_started", {"driver": "v", "model": "m"})
    path = tmp_path / ".agent-runtime" / "events" / "tsk_1.jsonl"
    line = path.read_text().splitlines()[0]
    obj = json.loads(line)
    assert obj["seq"] == 1
    assert obj["type"] == "task_started"
    assert "ts" in obj


def test_task_index_written_on_status(tmp_path):
    log = EventLog(workspace=str(tmp_path), task_id="tsk_1")
    log.write_status({"status": "completed", "result": {"success": True}})
    idx = tmp_path / ".agent-runtime" / "tasks" / "tsk_1.json"
    obj = json.loads(idx.read_text())
    assert obj["status"] == "completed"

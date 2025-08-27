import pytest

from shim.fswatch import classify_change, iter_relevant

pytestmark = pytest.mark.unit


def test_classify_added_modified_deleted(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    # watchfiles.Change values: 1=added, 2=modified, 3=deleted
    assert classify_change(1) == "create"
    assert classify_change(2) == "modify"
    assert classify_change(3) == "delete"


def test_iter_relevant_excludes_runtime_dir(tmp_path):
    ws = str(tmp_path)
    raw = {
        (2, str(tmp_path / "report.md")),
        (1, str(tmp_path / ".agent-runtime" / "events" / "t.jsonl")),
        (1, str(tmp_path / "data" / "out.json")),
    }
    rel = sorted(iter_relevant(raw, ws), key=lambda x: x[1])
    paths = [p for _, p in rel]
    assert "report.md" in paths
    assert "data/out.json" in paths
    assert all(not p.startswith(".agent-runtime") for p in paths)

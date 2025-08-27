# services/shim/tests/integration/container/test_files.py
import io
import zipfile

import pytest

from . import scripting as sc

pytestmark = pytest.mark.integration


def test_put_get_delete_round_trip(client):
    assert client.put("/files/raw", params={"path": "rt.txt"},
                      content=b"payload").status_code == 204
    got = client.get("/files/raw", params={"path": "rt.txt"})
    assert got.status_code == 200 and got.content == b"payload"
    assert client.delete("/files/raw", params={"path": "rt.txt"}
                        ).status_code == 204
    assert client.get("/files/raw", params={"path": "rt.txt"}
                     ).status_code == 404


def test_path_escape_rejected(client):
    assert client.get("/files/raw", params={"path": "../etc/passwd"}
                     ).status_code == 400


def test_reserved_dir_rejected(client):
    assert client.get("/files/raw",
                      params={"path": ".agent-runtime/status.json"}
                     ).status_code == 400


def test_missing_file_404(client):
    assert client.get("/files/raw", params={"path": "nope.txt"}
                     ).status_code == 404


def test_archive_contains_task_output(client):
    tid = "tsk_arch"
    turns = [{"tool": "write_file",
              "input": {"path": "arch.md", "content": "archived"}},
             {"done": {"success": True, "output": "ok"}}]
    client.post("/tasks", json=sc.task_body(tid, "vanilla", turns=turns))
    sc.poll_terminal(client, tid)
    archive = client.get("/files/archive")
    assert archive.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(archive.content))
    names = zf.namelist()
    assert any(n.endswith("arch.md") for n in names), names
    # Verify the archived bytes, not just the entry name — an empty/corrupt
    # file would otherwise pass the namelist check.
    match = next(n for n in names if n.endswith("arch.md"))
    assert zf.read(match) == b"archived"

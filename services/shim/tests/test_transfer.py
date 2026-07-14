"""expand_exports / stream_export_tar / extract_import_tar unit tests."""
from __future__ import annotations

import io
import os
import tarfile

import pytest

from shim.transfer import (
    TarImportError,
    expand_exports,
    extract_import_tar,
    stream_export_tar,
)

pytestmark = pytest.mark.unit


def _mk(ws, rel, content=b"x"):
    full = os.path.join(ws, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(content)
    return full


# ---- expand_exports ----------------------------------------------------------

def test_expand_exact_path_and_glob(tmp_path):
    ws = str(tmp_path)
    _mk(ws, "report.pdf", b"pdf")
    _mk(ws, "dist/a.js", b"aa")
    _mk(ws, "dist/sub/b.js", b"bbb")
    files, unmatched = expand_exports(ws, ["report.pdf", "dist/**"])
    assert unmatched == []
    assert [f["path"] for f in files] == ["dist/a.js", "dist/sub/b.js", "report.pdf"]
    assert {f["path"]: f["size"] for f in files}["dist/sub/b.js"] == 3


def test_expand_unmatched_pattern_reported(tmp_path):
    ws = str(tmp_path)
    _mk(ws, "a.txt")
    files, unmatched = expand_exports(ws, ["a.txt", "nope/**", "missing.bin"])
    assert [f["path"] for f in files] == ["a.txt"]
    assert unmatched == ["nope/**", "missing.bin"]


def test_expand_directory_only_match_is_unmatched(tmp_path):
    ws = str(tmp_path)
    os.makedirs(os.path.join(ws, "emptydir"))
    files, unmatched = expand_exports(ws, ["emptydir"])
    assert files == []
    assert unmatched == ["emptydir"]


def test_expand_excludes_reserved_git_and_symlinks(tmp_path):
    ws = str(tmp_path)
    _mk(ws, ".agent-runtime/events/e.jsonl")
    _mk(ws, ".git/config")
    _mk(ws, "nested/.git/HEAD")
    _mk(ws, "real.txt")
    os.symlink("/etc/hostname", os.path.join(ws, "link.txt"))
    files, unmatched = expand_exports(ws, ["**"])
    assert [f["path"] for f in files] == ["real.txt"]
    assert unmatched == []


def test_expand_dedupes_overlapping_patterns(tmp_path):
    ws = str(tmp_path)
    _mk(ws, "dist/a.js")
    files, unmatched = expand_exports(ws, ["dist/**", "dist/a.js"])
    assert [f["path"] for f in files] == ["dist/a.js"]
    assert unmatched == []


# ---- stream_export_tar ---------------------------------------------------------

def test_tar_round_trip(tmp_path):
    ws = str(tmp_path)
    _mk(ws, "report.pdf", b"pdf-bytes")
    _mk(ws, "dist/sub/b.js", b"js" * 100)
    files, _ = expand_exports(ws, ["report.pdf", "dist/**"])
    blob = b"".join(stream_export_tar(ws, files))
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tf:
        names = sorted(m.name for m in tf.getmembers())
        assert names == ["dist/sub/b.js", "report.pdf"]
        assert tf.extractfile("report.pdf").read() == b"pdf-bytes"
        assert tf.extractfile("dist/sub/b.js").read() == b"js" * 100


# ---- extract_import_tar --------------------------------------------------------

def _tar_bytes(*members):
    """members: (name, content-bytes | None for dir | TarInfo for raw)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, content in members:
            if isinstance(name, tarfile.TarInfo):
                tf.addfile(name)
                continue
            if content is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
            else:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _spool(tmp_path, blob):
    p = str(tmp_path / "in.tar")
    with open(p, "wb") as fh:
        fh.write(blob)
    return p


def test_extract_writes_files_and_overwrites(tmp_path):
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    _mk(ws, "dist/a.js", b"old")
    blob = _tar_bytes(("dist", None), ("dist/a.js", b"new"), ("top.txt", b"t"))
    out = extract_import_tar(ws, _spool(tmp_path, blob))
    assert out == {"files_written": 2, "bytes_written": 4}
    assert open(os.path.join(ws, "dist/a.js"), "rb").read() == b"new"
    assert open(os.path.join(ws, "top.txt"), "rb").read() == b"t"


@pytest.mark.parametrize("bad", ["/abs.txt", "../escape.txt", "a/../../up.txt",
                                 ".git/config", ".agent-runtime/x", "a/.git/hook"])
def test_extract_rejects_bad_paths(tmp_path, bad):
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    blob = _tar_bytes((bad, b"evil"))
    with pytest.raises(TarImportError):
        extract_import_tar(ws, _spool(tmp_path, blob))


def test_extract_rejects_symlink_member(tmp_path):
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    info = tarfile.TarInfo("link.txt")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    blob = _tar_bytes((info, None))
    with pytest.raises(TarImportError):
        extract_import_tar(ws, _spool(tmp_path, blob))

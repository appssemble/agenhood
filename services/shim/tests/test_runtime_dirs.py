"""Runtime-dir layout: .agent-runtime must be traversable (711) so sandboxed
uid-1000 subprocesses (bash/python tools) can reach the skills subtree by
name, while the shim-private children (events/tasks/tmp) stay 700."""
import os
import stat

import pytest

from shim.main import prepare_runtime_dirs

pytestmark = pytest.mark.unit


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_creates_layout_with_correct_modes(tmp_path):
    prepare_runtime_dirs(str(tmp_path))
    base = tmp_path / ".agent-runtime"
    assert _mode(str(base)) == 0o711
    for child in ("events", "tasks", "tmp"):
        assert _mode(str(base / child)) == 0o700, child


def test_corrects_modes_on_existing_dirs(tmp_path):
    # A volume created by an older image: 700 base, 755 children.
    base = tmp_path / ".agent-runtime"
    (base / "events").mkdir(parents=True)
    os.chmod(base, 0o700)
    os.chmod(base / "events", 0o755)
    prepare_runtime_dirs(str(tmp_path))
    assert _mode(str(base)) == 0o711
    assert _mode(str(base / "events")) == 0o700
    # Pre-existing content is untouched.
    assert (base / "events").exists()


def test_idempotent(tmp_path):
    prepare_runtime_dirs(str(tmp_path))
    prepare_runtime_dirs(str(tmp_path))
    assert _mode(str(tmp_path / ".agent-runtime")) == 0o711

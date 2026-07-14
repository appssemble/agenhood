from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.drivers.opencode import opencode_config_path, write_opencode_mcp, workspace_xdg
from agentcore.models import ShimMcpServer

pytestmark = pytest.mark.unit


def test_config_path_under_xdg_config(tmp_path):
    expected = Path(workspace_xdg(str(tmp_path))["XDG_CONFIG_HOME"]) / "opencode" / "opencode.json"
    assert opencode_config_path(str(tmp_path)) == str(expected)


def test_write_creates_mcp_block(tmp_path):
    n = write_opencode_mcp(str(tmp_path), [
        ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="t"),
    ])
    assert n == 1
    data = json.loads(Path(opencode_config_path(str(tmp_path))).read_text())
    assert data["mcp"]["lin"]["headers"]["Authorization"] == "Bearer t"


def test_write_merges_into_existing_config(tmp_path):
    p = Path(opencode_config_path(str(tmp_path)))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"theme": "dark"}))
    write_opencode_mcp(str(tmp_path), [ShimMcpServer(name="pub", url="https://m")])
    data = json.loads(p.read_text())
    assert data["theme"] == "dark"          # preserved
    assert "pub" in data["mcp"]


def test_write_empty_is_noop(tmp_path):
    assert write_opencode_mcp(str(tmp_path), []) == 0
    assert not Path(opencode_config_path(str(tmp_path))).exists()


def test_write_empty_clears_prior_mcp_block(tmp_path):
    """Writing an empty server list clears a prior mcp block but preserves other keys."""
    # First write: populate an mcp entry with a secret
    write_opencode_mcp(str(tmp_path), [
        ShimMcpServer(name="lin", url="https://m", auth_type="bearer", secret="tok"),
    ])
    # Inject an unrelated top-level key (simulates other opencode config)
    p = Path(opencode_config_path(str(tmp_path)))
    data = json.loads(p.read_text())
    data["theme"] = "dark"
    p.write_text(json.dumps(data))
    # Second write: empty list should clear mcp, not leave stale secrets
    n = write_opencode_mcp(str(tmp_path), [])
    assert n == 0
    data = json.loads(p.read_text())
    assert data["mcp"] == {}          # cleared
    assert "lin" not in data["mcp"]   # old server and its secret are gone
    assert data["theme"] == "dark"    # unrelated key preserved


def test_write_replaces_unwritable_existing_file(tmp_path):
    """A prior task's opencode process (agent uid) owns opencode.json; the shim
    (root, no CAP_FOWNER) gets EPERM from in-place write/chmod. The writer must
    unlink and recreate — simulated here with a read-only existing file, which
    in-place write_text cannot modify but unlink-and-recreate can."""
    p = Path(opencode_config_path(str(tmp_path)))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"theme": "dark", "mcp": {"old": {}}}))
    p.chmod(0o400)
    n = write_opencode_mcp(str(tmp_path), [ShimMcpServer(name="new", url="https://m")])
    assert n == 1
    data = json.loads(p.read_text())
    assert data["theme"] == "dark"          # non-mcp keys still preserved
    assert list(data["mcp"]) == ["new"]

from __future__ import annotations

import pytest

from control_plane.ids import new_mcp_id
from control_plane.models_db import metadata

pytestmark = pytest.mark.unit


def test_new_mcp_id_prefix() -> None:
    mid = new_mcp_id()
    assert mid.startswith("mcp_")
    assert mid == mid.lower()


def test_mcp_servers_table_registered() -> None:
    assert "mcp_servers" in metadata.tables
    cols = {c.name for c in metadata.tables["mcp_servers"].columns}
    assert {"id", "tenant_id", "name", "description", "url",
            "auth_type", "auth_header_name", "secret_ciphertext", "enabled"} <= cols

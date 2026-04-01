import pytest

pytestmark = pytest.mark.unit


def test_templates_table_has_mcp_servers_column() -> None:
    from control_plane.models_db import templates
    assert "mcp_servers" in set(templates.c.keys())

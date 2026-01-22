# services/control_plane/tests/test_skills_ids.py
from __future__ import annotations

import pytest

from control_plane.ids import new_skill_id
from control_plane.models_db import metadata

pytestmark = pytest.mark.unit


def test_new_skill_id_prefix() -> None:
    sid = new_skill_id()
    assert sid.startswith("skl_")
    assert sid == sid.lower()


def test_skills_table_registered() -> None:
    assert "skills" in metadata.tables
    cols = {c.name for c in metadata.tables["skills"].columns}
    assert {"id", "tenant_id", "name", "description", "body", "enabled"} <= cols

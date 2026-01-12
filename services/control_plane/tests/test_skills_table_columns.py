import pytest

pytestmark = pytest.mark.unit


def test_skills_table_has_source_columns() -> None:
    from control_plane.models_db import skills
    cols = set(skills.c.keys())
    for c in (
        "source_type", "source_url", "source_subpath", "source_ref",
        "pinned_sha", "bundle", "bundle_sha256", "bundle_size",
    ):
        assert c in cols, f"missing column {c}"

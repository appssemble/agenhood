import pytest

pytestmark = pytest.mark.unit


def test_prompts_table_has_expected_columns() -> None:
    from control_plane.models_db import prompts
    assert set(prompts.c.keys()) == {
        "id", "tenant_id", "name", "body", "tags", "variables",
        "created_by", "created_at", "updated_at",
    }


def test_new_prompt_id_prefix() -> None:
    from control_plane.ids import new_prompt_id
    pid = new_prompt_id()
    assert pid.startswith("prm_")
    assert pid == pid.lower()

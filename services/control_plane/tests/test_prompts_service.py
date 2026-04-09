from __future__ import annotations

import pytest

from control_plane.errors import APIError
from control_plane.prompts_service import (
    build_prompt_row,
    extract_variables,
    normalize_tags,
    prompt_view,
    reconcile_variables,
    validate_prompt_fields,
)

pytestmark = pytest.mark.unit


def test_extract_variables_order_and_dedup() -> None:
    body = "Hi {{team}}, week of {{ date }}. Again {{team}}."
    assert extract_variables(body) == ["team", "date"]


def test_extract_variables_ignores_malformed() -> None:
    assert extract_variables("no vars { {x}} {{}} {{1a-b}}") == []


def test_reconcile_keeps_known_meta_drops_stale() -> None:
    body = "{{team}} and {{audience}}"
    meta = [
        {"name": "team", "label": "Team", "default": ""},
        {"name": "gone", "label": "Old", "default": "x"},
    ]
    out = reconcile_variables(body, meta)
    assert [v["name"] for v in out] == ["team", "audience"]
    assert out[0] == {"name": "team", "label": "Team", "default": ""}
    assert out[1] == {"name": "audience", "label": "", "default": ""}


def test_normalize_tags_trims_dedup_lowercases_nothing() -> None:
    assert normalize_tags(["  Report ", "report", "weekly", ""]) == ["Report", "weekly"]


def test_normalize_tags_rejects_non_list() -> None:
    with pytest.raises(APIError) as exc:
        normalize_tags("report")
    assert exc.value.field == "tags"


def test_validate_rejects_blank_name() -> None:
    with pytest.raises(APIError) as exc:
        validate_prompt_fields(name="   ", body="x", tags=[])
    assert exc.value.field == "name"


def test_validate_rejects_blank_body() -> None:
    with pytest.raises(APIError) as exc:
        validate_prompt_fields(name="ok", body="", tags=[])
    assert exc.value.field == "body"


def test_build_row_and_view_roundtrip() -> None:
    row = build_prompt_row(
        tenant_id="ten_1", created_by="usr_1", name="Weekly",
        body="Hi {{team}}", tags=["report"],
        variables=[{"name": "team", "label": "Team", "default": ""}],
    )
    assert row["id"].startswith("prm_")
    assert row["tenant_id"] == "ten_1"
    view = prompt_view(row)
    assert "tenant_id" not in view
    assert view["name"] == "Weekly"
    assert view["tags"] == ["report"]
    assert view["variables"][0]["name"] == "team"

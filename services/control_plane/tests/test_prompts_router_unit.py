from __future__ import annotations

import pytest

from control_plane.errors import APIError
from control_plane.routers.prompts import apply_prompt_patch, parse_prompt_create

pytestmark = pytest.mark.unit


def test_parse_create_derives_variables() -> None:
    out = parse_prompt_create({
        "name": "Weekly", "body": "Hi {{team}} on {{date}}",
        "tags": ["report", "report"],
        "variables": [{"name": "team", "label": "Team"}],
    })
    assert out["name"] == "Weekly"
    assert out["tags"] == ["report"]
    assert [v["name"] for v in out["variables"]] == ["team", "date"]
    assert out["variables"][0]["label"] == "Team"


def test_parse_create_requires_name() -> None:
    with pytest.raises(APIError) as exc:
        parse_prompt_create({"body": "x"})
    assert exc.value.field == "name"


def test_parse_create_requires_body() -> None:
    with pytest.raises(APIError) as exc:
        parse_prompt_create({"name": "ok"})
    assert exc.value.field == "body"


def test_patch_reextracts_variables_on_body_change() -> None:
    existing = {
        "name": "Weekly", "body": "Hi {{team}}", "tags": ["report"],
        "variables": [{"name": "team", "label": "Team", "default": ""}],
    }
    merged = apply_prompt_patch(existing, {"body": "Hi {{team}} and {{audience}}"})
    assert [v["name"] for v in merged["variables"]] == ["team", "audience"]
    # label retained for surviving variable
    assert merged["variables"][0]["label"] == "Team"


def test_patch_partial_keeps_existing_name() -> None:
    existing = {"name": "Weekly", "body": "Hi {{team}}", "tags": [],
                "variables": [{"name": "team", "label": "", "default": ""}]}
    merged = apply_prompt_patch(existing, {"tags": ["new"]})
    assert merged["name"] == "Weekly"
    assert merged["tags"] == ["new"]

# services/control_plane/tests/test_skills_router_unit.py
from __future__ import annotations

import pytest

from control_plane.errors import APIError
from control_plane.routers.skills import apply_skill_patch, parse_skill_create

pytestmark = pytest.mark.unit


def test_parse_create_defaults_enabled_true() -> None:
    out = parse_skill_create({"name": "git-release", "description": "d"})
    assert out == {
        "name": "git-release", "description": "d",
        "body": "", "enabled": True, "source_type": "inline",
    }


def test_parse_create_validates() -> None:
    with pytest.raises(APIError) as exc:
        parse_skill_create({"name": "Bad", "description": "d"})
    assert exc.value.field == "name"


def test_parse_create_requires_name_and_description() -> None:
    with pytest.raises(APIError):
        parse_skill_create({"description": "d"})       # missing name
    with pytest.raises(APIError):
        parse_skill_create({"name": "ok"})             # missing description


def test_apply_patch_merges_and_validates() -> None:
    existing = {"name": "git-release", "description": "old", "body": "b", "enabled": True}
    out = apply_skill_patch(existing, {"description": "new", "enabled": False})
    assert out["description"] == "new"
    assert out["enabled"] is False
    assert out["name"] == "git-release"                 # unchanged


def test_apply_patch_rejects_bad_field() -> None:
    existing = {"name": "ok", "description": "d", "body": "", "enabled": True}
    with pytest.raises(APIError) as exc:
        apply_skill_patch(existing, {"name": "Bad Name"})
    assert exc.value.field == "name"


def test_parse_skill_create_inline_default() -> None:
    out = parse_skill_create({"name": "x", "description": "d", "body": "b"})
    assert out["source_type"] == "inline"


def test_parse_skill_create_git_requires_url() -> None:
    with pytest.raises(APIError):
        parse_skill_create({"source_type": "git", "source_ref": "main"})


def test_parse_skill_create_git_fields() -> None:
    out = parse_skill_create({
        "source_type": "git", "source_url": "https://x/y",
        "source_subpath": "skills/pdf", "source_ref": "v1",
    })
    assert out["source_type"] == "git"
    assert out["source_url"] == "https://x/y"
    assert out["source_subpath"] == "skills/pdf"
    assert out["source_ref"] == "v1"

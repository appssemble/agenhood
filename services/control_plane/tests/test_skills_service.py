# services/control_plane/tests/test_skills_service.py
from __future__ import annotations

import base64

import pytest

from control_plane.errors import APIError
from control_plane.skills_service import (
    build_skill_row,
    normalize_description,
    resolve_skills_for_request,
    skill_detail_view,
    skill_public_view,
    validate_skill_fields,
)

pytestmark = pytest.mark.unit


def test_validate_ok() -> None:
    validate_skill_fields(name="git-release", description="Make releases", body="x")


@pytest.mark.parametrize("name", ["Bad", "-x", "x-", "a--b", "has space", "", "z" * 65])
def test_validate_rejects_bad_name(name: str) -> None:
    with pytest.raises(APIError) as exc:
        validate_skill_fields(name=name, description="d", body="")
    assert exc.value.field == "name"


@pytest.mark.parametrize("desc", ["", "z" * 1025])
def test_validate_rejects_bad_description(desc: str) -> None:
    with pytest.raises(APIError) as exc:
        validate_skill_fields(name="ok", description=desc, body="")
    assert exc.value.field == "description"


def test_validate_rejects_oversized_body() -> None:
    with pytest.raises(APIError) as exc:
        validate_skill_fields(name="ok", description="d", body="z" * (64 * 1024 + 1))
    assert exc.value.field == "body"


def test_build_row_sets_fields() -> None:
    row = build_skill_row(
        tenant_id="ten_1", name="git-release", description="d", body="b",
        enabled=True, created_by="usr_1",
    )
    assert row["id"].startswith("skl_")
    assert row["tenant_id"] == "ten_1"
    assert row["name"] == "git-release"
    assert row["enabled"] is True


def _row() -> dict:
    return {"id": "skl_1", "tenant_id": "ten_1", "name": "git-release",
            "description": "d", "body": "b", "enabled": True,
            "created_by": "u", "created_at": "t", "updated_at": "t"}


def test_public_view_is_a_summary_without_body_or_tenant() -> None:
    v = skill_public_view(_row())
    assert v["id"] == "skl_1" and v["name"] == "git-release"
    assert v["description"] == "d" and v["enabled"] is True
    assert "tenant_id" not in v
    assert "body" not in v               # list view never ships the body


def test_detail_view_includes_body() -> None:
    v = skill_detail_view(_row())
    assert v["body"] == "b"
    assert "tenant_id" not in v
    assert v["name"] == "git-release"


@pytest.mark.parametrize("raw,expected", [
    ("line1\nline2", "line1 line2"),
    ("line1\r\nline2\r\nline3", "line1 line2 line3"),
    ("  spaced   out  ", "spaced out"),
    ("single", "single"),
])
def test_normalize_description_collapses_newlines(raw: str, expected: str) -> None:
    assert normalize_description(raw) == expected


def test_resolve_filters_enabled_and_membership_and_preserves_order() -> None:
    rows = [
        {"id": "skl_a", "name": "a", "description": "da", "body": "ba", "enabled": True},
        {"id": "skl_b", "name": "b", "description": "db", "body": "bb", "enabled": False},
        {"id": "skl_c", "name": "c", "description": "dc", "body": "bc", "enabled": True},
    ]
    # selection order b, c, a, missing — disabled b and unknown id dropped.
    out = resolve_skills_for_request(["skl_b", "skl_c", "skl_a", "skl_zzz"], rows)
    assert [s.name for s in out] == ["c", "a"]
    assert out[0].description == "dc" and out[0].body == "bc"


def test_filter_known_skill_ids_preserves_order_and_drops_unknown() -> None:
    from control_plane.skills_service import filter_known_skill_ids

    rows = [{"id": "skl_a"}, {"id": "skl_b"}]
    assert filter_known_skill_ids(["skl_b", "skl_zzz", "skl_a"], rows) == ["skl_b", "skl_a"]
    assert filter_known_skill_ids([], rows) == []


def test_skill_public_view_includes_source_fields() -> None:
    from control_plane.skills_service import skill_public_view
    row = {
        "id": "skl_1", "name": "pdf", "description": "d", "enabled": True,
        "created_at": None, "updated_at": None,
        "source_type": "git", "source_url": "https://x/y",
        "source_subpath": "skills/pdf", "source_ref": "main",
        "pinned_sha": "a" * 40, "bundle_size": 1234,
    }
    v = skill_public_view(row)
    assert v["source_type"] == "git"
    assert v["pinned_sha"] == "a" * 40
    assert v["bundle_size"] == 1234
    assert "bundle" not in v  # never expose raw bytes


def test_build_git_skill_row() -> None:
    from control_plane.skills_fetch import FetchedSkill
    from control_plane.skills_service import build_git_skill_row
    fetched = FetchedSkill(
        name="pdf", description="Edit PDFs", body="b", pinned_sha="a" * 40,
        bundle=b"gz", bundle_sha256="f" * 64, bundle_size=42,
    )
    row = build_git_skill_row(
        tenant_id="t1", created_by="u1", enabled=True,
        source_url="https://x/y", source_subpath="skills/pdf",
        source_ref="main", fetched=fetched,
    )
    assert row["source_type"] == "git"
    assert row["name"] == "pdf"
    assert row["pinned_sha"] == "a" * 40
    assert row["bundle"] == b"gz"
    assert row["bundle_size"] == 42
    assert row["id"].startswith("skl_")


def test_resolve_ships_bundle_b64_for_git_rows() -> None:
    from control_plane.skills_service import resolve_skills_for_request
    rows = [
        {"id": "a", "name": "inline", "description": "d", "body": "hi",
         "enabled": True, "source_type": "inline", "bundle": None,
         "bundle_size": None},
        {"id": "b", "name": "pdf", "description": "d", "body": "",
         "enabled": True, "source_type": "git", "bundle": b"gzbytes",
         "bundle_size": 7},
    ]
    out = resolve_skills_for_request(["a", "b"], rows)
    assert out[0].body == "hi" and out[0].bundle_b64 is None
    assert out[1].bundle_b64 == base64.b64encode(b"gzbytes").decode()


def test_resolve_caps_total_bundle_bytes() -> None:
    from control_plane.skills_service import (
        MAX_TASK_BUNDLE_BYTES,
        resolve_skills_for_request,
    )
    big = MAX_TASK_BUNDLE_BYTES // 2 + 1
    rows = [
        {"id": "a", "name": "one", "description": "d", "body": "",
         "enabled": True, "source_type": "git", "bundle": b"x",
         "bundle_size": big},
        {"id": "b", "name": "two", "description": "d", "body": "",
         "enabled": True, "source_type": "git", "bundle": b"x",
         "bundle_size": big},
    ]
    out = resolve_skills_for_request(["a", "b"], rows)
    # First fits; second pushes over the cap and is dropped.
    assert [s.name for s in out] == ["one"]

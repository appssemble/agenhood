from __future__ import annotations

import pytest

from control_plane.errors import APIError
from control_plane.routers.mcp_servers import apply_mcp_patch, parse_mcp_create

pytestmark = pytest.mark.unit


def test_parse_create_defaults() -> None:
    out = parse_mcp_create({"name": "linear", "description": "d", "url": "https://m"})
    assert out["auth_type"] == "none"
    assert out["enabled"] is True
    assert out["secret"] == ""


def test_parse_create_bearer() -> None:
    out = parse_mcp_create({"name": "linear", "description": "d", "url": "https://m",
                            "auth_type": "bearer", "secret": "tok"})
    assert out["auth_type"] == "bearer"
    assert out["secret"] == "tok"


def test_parse_create_rejects_http() -> None:
    with pytest.raises(APIError) as exc:
        parse_mcp_create({"name": "linear", "description": "d", "url": "http://m"})
    assert exc.value.field == "url"


def test_patch_keep_secret_when_absent() -> None:
    existing = {"name": "linear", "description": "d", "url": "https://m",
                "auth_type": "bearer", "auth_header_name": None,
                "secret_ciphertext": b"x", "enabled": True}
    merged, directive = apply_mcp_patch(existing, {"description": "new"})
    assert merged["description"] == "new"
    assert directive == "keep"


def test_patch_set_secret_when_value_given() -> None:
    existing = {"name": "linear", "description": "d", "url": "https://m",
                "auth_type": "bearer", "auth_header_name": None,
                "secret_ciphertext": b"x", "enabled": True}
    merged, directive = apply_mcp_patch(existing, {"secret": "new-token"})
    assert directive == "set"
    assert merged["secret"] == "new-token"


def test_patch_clear_secret_on_empty_string() -> None:
    existing = {"name": "linear", "description": "d", "url": "https://m",
                "auth_type": "none", "auth_header_name": None,
                "secret_ciphertext": b"x", "enabled": True}
    _, directive = apply_mcp_patch(existing, {"secret": ""})
    assert directive == "clear"

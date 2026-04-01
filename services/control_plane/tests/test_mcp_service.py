from __future__ import annotations

import pytest

from control_plane.auth.crypto import encrypt_secret
from control_plane.errors import APIError
from control_plane.mcp_service import (
    build_mcp_row,
    mcp_public_view,
    resolve_mcp_for_request,
    validate_mcp_fields,
)

pytestmark = pytest.mark.unit

KEY = b"0" * 32


def test_validate_rejects_non_https() -> None:
    with pytest.raises(APIError) as exc:
        validate_mcp_fields(name="a", description="d", url="http://x",
                            auth_type="none", auth_header_name=None, has_secret=False)
    assert exc.value.field == "url"


def test_validate_rejects_bad_name() -> None:
    with pytest.raises(APIError) as exc:
        validate_mcp_fields(name="Bad Name", description="d", url="https://x",
                            auth_type="none", auth_header_name=None, has_secret=False)
    assert exc.value.field == "name"


def test_validate_bearer_requires_secret() -> None:
    with pytest.raises(APIError) as exc:
        validate_mcp_fields(name="a", description="d", url="https://x",
                            auth_type="bearer", auth_header_name=None, has_secret=False)
    assert exc.value.field == "secret"


def test_validate_header_requires_header_name() -> None:
    with pytest.raises(APIError) as exc:
        validate_mcp_fields(name="a", description="d", url="https://x",
                            auth_type="header", auth_header_name="", has_secret=True)
    assert exc.value.field == "auth_header_name"


def test_validate_rejects_unknown_auth_type() -> None:
    with pytest.raises(APIError) as exc:
        validate_mcp_fields(name="a", description="d", url="https://x",
                            auth_type="oauth", auth_header_name=None, has_secret=False)
    assert exc.value.field == "auth_type"


def test_build_row_encrypts_secret() -> None:
    row = build_mcp_row(tenant_id="ten_1", created_by="u", name="a", description="d",
                        url="https://x", auth_type="bearer", auth_header_name=None,
                        secret="t0k", enabled=True, master_key=KEY)
    assert row["secret_ciphertext"] is not None
    assert b"t0k" not in row["secret_ciphertext"]   # encrypted, not plaintext
    assert row["id"].startswith("mcp_")


def test_public_view_hides_secret_and_flags_set() -> None:
    row = build_mcp_row(tenant_id="ten_1", created_by="u", name="a", description="d",
                        url="https://x", auth_type="bearer", auth_header_name=None,
                        secret="t0k", enabled=True, master_key=KEY)
    view = mcp_public_view(row)
    assert "secret_ciphertext" not in view
    assert "tenant_id" not in view
    assert view["secret_set"] is True
    assert view["auth_type"] == "bearer"


def test_resolve_decrypts_and_orders_and_filters() -> None:
    rows = [
        {"id": "mcp_a", "name": "a", "url": "https://a", "auth_type": "bearer",
         "auth_header_name": None, "secret_ciphertext": encrypt_secret("ta", KEY), "enabled": True},
        {"id": "mcp_b", "name": "b", "url": "https://b", "auth_type": "none",
         "auth_header_name": None, "secret_ciphertext": None, "enabled": True},
        {"id": "mcp_c", "name": "c", "url": "https://c", "auth_type": "none",
         "auth_header_name": None, "secret_ciphertext": None, "enabled": False},
    ]
    out = resolve_mcp_for_request(["mcp_b", "mcp_a", "mcp_c", "mcp_x"], rows, KEY)
    assert [s.name for s in out] == ["b", "a"]      # order preserved; disabled+unknown dropped
    assert out[1].secret == "ta"                    # decrypted

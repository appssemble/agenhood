from __future__ import annotations

from control_plane.routers.api_keys import build_api_key_row, public_view


def test_build_row_stores_hash_and_prefix_not_secret() -> None:
    secret, row = build_api_key_row(tenant_id="ten_1", name="ci", created_by="usr_1")
    assert secret.startswith("tk_live_")
    assert row["key_prefix"] == secret[:8]
    assert row["key_hash"] != secret              # Argon2id, not plaintext
    assert secret not in row.values()
    assert row["status"] == "active"


def test_public_view_omits_hash() -> None:
    row = {
        "id": "key_1",
        "name": "ci",
        "key_prefix": "tk_live_",
        "key_hash": "$argon2id$...",
        "created_by": "usr_1",
        "last_used_at": None,
        "created_at": "t",
        "status": "active",
    }
    v = public_view(row)
    assert "key_hash" not in v
    assert v["prefix"] == "tk_live_"
    assert v["id"] == "key_1"

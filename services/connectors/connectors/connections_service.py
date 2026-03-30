from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from connectors.crypto import decrypt_secret, encrypt_secret
from connectors.ids import new_id


def build_connection_row(
    *,
    tenant_id: str,
    provider: str,
    external_id: str,
    display_name: str,
    access_token: str | None,
    refresh_token: str | None,
    token_expires_at: datetime | None,
    cp_api_key: str | None,
    scopes: str,
    metadata: dict[str, Any],
    master_key: bytes,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": new_id("con"),
        "tenant_id": tenant_id,
        "provider": provider,
        "external_id": external_id,
        "display_name": display_name,
        "status": "active",
        "access_token_ciphertext": (
            encrypt_secret(access_token, master_key) if access_token else None
        ),
        "refresh_token_ciphertext": (
            encrypt_secret(refresh_token, master_key) if refresh_token else None
        ),
        "token_expires_at": token_expires_at,
        "cp_api_key_ciphertext": (
            encrypt_secret(cp_api_key, master_key) if cp_api_key else None
        ),
        "scopes": scopes,
        "connection_metadata": metadata,
        "_access_token_last4": (access_token or "")[-4:],  # for view convenience
        "created_at": now,
        "updated_at": now,
    }


def decrypt_access_token(row: dict[str, Any], master_key: bytes) -> str:
    return decrypt_secret(row["access_token_ciphertext"], master_key)


def decrypt_cp_api_key(row: dict[str, Any], master_key: bytes) -> str:
    return decrypt_secret(row["cp_api_key_ciphertext"], master_key)


def public_connection_view(row: dict[str, Any]) -> dict[str, Any]:
    last4 = row.get("_access_token_last4")
    if last4 is None:
        # Row came from the DB: derive nothing from ciphertext; show empty.
        last4 = ""
    return {
        "id": row["id"],
        "provider": row["provider"],
        "external_id": row["external_id"],
        "display_name": row["display_name"],
        "status": row["status"],
        "scopes": row["scopes"],
        "token_last4": last4,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }

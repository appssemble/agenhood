"""Pure helpers for workspace-scoped skill deploy keys.

Same secrecy rules as git_remotes_service (whose keygen we reuse): AES-GCM
ciphertext at rest, plaintext in memory only, public half + fingerprint are the
only things any endpoint returns.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from control_plane.auth.crypto import decrypt_secret, encrypt_secret
from control_plane.git_remotes_service import generate_deploy_key
from control_plane.ids import new_deploy_key_id

MAX_NAME = 64


def build_deploy_key_row(
    *, tenant_id: str, name: str, master_key: bytes
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > MAX_NAME:
        raise ValueError(f"name exceeds {MAX_NAME} chars")
    keypair = generate_deploy_key(comment=f"agenhood-skill-{name}")
    now = datetime.now(UTC)
    return {
        "id": new_deploy_key_id(),
        "tenant_id": tenant_id,
        "name": name,
        "ssh_private_key_ciphertext": encrypt_secret(keypair.private_key, master_key),
        "ssh_public_key": keypair.public_key,
        "key_type": keypair.key_type,
        "key_fingerprint": keypair.fingerprint,
        "created_at": now,
        "updated_at": now,
    }


def deploy_key_public_view(row: dict[str, Any]) -> dict[str, Any]:
    """What every GET returns — never the private key or its ciphertext."""
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "ssh_public_key": row["ssh_public_key"],
        "key_type": row["key_type"],
        "key_fingerprint": row["key_fingerprint"],
        "created_at": created.isoformat() if created else None,
        "updated_at": updated.isoformat() if updated else None,
    }


def decrypt_deploy_key(row: dict[str, Any], master_key: bytes) -> str:
    return decrypt_secret(row["ssh_private_key_ciphertext"], master_key)

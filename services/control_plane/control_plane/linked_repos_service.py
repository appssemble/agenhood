"""Pure helpers for per-container linked repos (pull mode).

Mirrors git_remotes_service for the linked-repo (clone source) flow. The pull
deploy key follows the same secret-handling rules: ciphertext at rest, never in
any GET response.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from control_plane.auth.crypto import encrypt_secret
from control_plane.git_remotes_service import (
    DeployKey,
    validate_branch,
    validate_remote_url,
)


def build_linked_row(
    *,
    container_id: str,
    url: str,
    branch: str,
    keypair: DeployKey,
    master_key: bytes,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "container_id": container_id,
        "url": validate_remote_url(url),
        "branch": validate_branch(branch),
        "ssh_private_key_ciphertext": encrypt_secret(keypair.private_key, master_key),
        "ssh_public_key": keypair.public_key,
        "key_type": keypair.key_type,
        "key_fingerprint": keypair.fingerprint,
        "updated_at": now,
    }


def public_linked_view(row: dict[str, Any]) -> dict[str, Any]:
    """What GET /git/link returns — never the private key or ciphertext."""
    def _iso(v: Any) -> str | None:
        return v.isoformat() if v else None

    return {
        "url": row["url"],
        "branch": row["branch"],
        "ssh_public_key": row.get("ssh_public_key"),
        "key_fingerprint": row.get("key_fingerprint"),
        "key_type": row.get("key_type"),
        "verified_at": _iso(row.get("verified_at")),
        "linked_at": _iso(row.get("linked_at")),
        "last_clone_status": row.get("last_clone_status"),
        "last_clone_error": row.get("last_clone_error"),
        "last_clone_at": _iso(row.get("last_clone_at")),
    }

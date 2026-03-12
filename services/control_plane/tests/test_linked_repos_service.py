from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from control_plane.git_remotes_service import decrypt_private_key, generate_deploy_key
from control_plane.linked_repos_service import build_linked_row, public_linked_view

pytestmark = pytest.mark.unit

KEY = os.urandom(32)


def test_build_linked_row_encrypts_key_and_validates() -> None:
    kp = generate_deploy_key()
    row = build_linked_row(
        container_id="c1", url="git@github.com:o/r.git", branch="main",
        keypair=kp, master_key=KEY,
    )
    assert row["container_id"] == "c1"
    assert row["url"] == "git@github.com:o/r.git"
    assert row["branch"] == "main"
    assert row["ssh_public_key"] == kp.public_key
    # round-trips back to the private key
    assert decrypt_private_key(row, KEY) == kp.private_key


def test_build_linked_row_rejects_http_url() -> None:
    kp = generate_deploy_key()
    with pytest.raises(ValueError):
        build_linked_row(
            container_id="c1", url="https://github.com/o/r.git", branch="main",
            keypair=kp, master_key=KEY,
        )


def test_public_linked_view_omits_secrets() -> None:
    view = public_linked_view({
        "url": "git@h:o/r.git", "branch": "main",
        "ssh_public_key": "ssh-ed25519 AAA x", "key_fingerprint": "SHA256:z",
        "key_type": "ed25519", "ssh_private_key_ciphertext": b"SECRET",
        "verified_at": datetime.now(UTC), "linked_at": datetime.now(UTC),
        "last_clone_status": "cloned", "last_clone_error": None,
        "last_clone_at": datetime.now(UTC),
    })
    assert "ssh_private_key_ciphertext" not in view
    assert view["ssh_public_key"] == "ssh-ed25519 AAA x"
    assert view["last_clone_status"] == "cloned"
    assert isinstance(view["linked_at"], str)

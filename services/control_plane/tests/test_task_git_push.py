# services/control_plane/tests/test_task_git_push.py
from __future__ import annotations

import os

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from control_plane.auth.crypto import encrypt_secret
from control_plane.routers.tasks import build_git_push, build_shim_request

pytestmark = pytest.mark.unit

KEY = os.urandom(32)

_FAKE_PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"


def _remote_row(enabled: bool = True) -> dict:
    """Minimal git_remotes row using the SSH keypair model."""
    return {
        "container_id": "ctr_1",
        "url": "git@github.com:a/b.git",
        "branch": "trunk",
        "ssh_private_key_ciphertext": encrypt_secret(_FAKE_PRIVATE_KEY, KEY),
        "ssh_public_key": "ssh-ed25519 AAAA… agenhood",
        "key_type": "ed25519",
        "key_fingerprint": "SHA256:abc123",
        "enabled": enabled,
    }


def test_build_git_push_decrypts_ssh_key() -> None:
    gp = build_git_push(_remote_row(), KEY)
    assert gp is not None
    assert gp.url == "git@github.com:a/b.git"
    assert gp.branch == "trunk"
    assert gp.ssh_private_key == _FAKE_PRIVATE_KEY


def test_build_git_push_none_when_disabled_or_missing() -> None:
    assert build_git_push(_remote_row(enabled=False), KEY) is None
    assert build_git_push(None, KEY) is None


def test_build_git_push_none_when_no_ssh_key_ciphertext() -> None:
    row = _remote_row()
    row["ssh_private_key_ciphertext"] = None
    assert build_git_push(row, KEY) is None


def test_shim_request_carries_git_push_but_task_row_never_does() -> None:
    from control_plane.routers.tasks import build_task_row

    task = TaskBody(prompt="hi")
    config = AgentConfig(driver="vanilla", model="m")
    limits = ResolvedLimits(max_iterations=5, max_tokens=100, timeout_seconds=30)
    gp = build_git_push(_remote_row(), KEY)
    req = build_shim_request(
        task_id="tsk_1", task=task, config=config, limits=limits,
        credential="sk", git_push=gp,
    )
    assert req.git_push is gp
    row = build_task_row(
        task_id="tsk_1", tenant_id="t", container_id="c", task=task, config=config
    )
    assert _FAKE_PRIVATE_KEY not in str(row)          # key never persisted
    assert "ssh_private_key" not in str(row)


def test_git_push_event_values() -> None:
    from control_plane.routers.tasks import git_event_remote_values

    ok = git_event_remote_values({"op": "push", "ok": True, "sha": "a" * 40})
    assert ok is not None and ok["last_push_status"] == "pushed"
    failed = git_event_remote_values({"op": "push", "ok": False,
                                      "error": "push_auth_failed"})
    assert failed is not None
    assert failed["last_push_status"] == "failed"
    assert failed["last_push_error"] == "push_auth_failed"
    # commit events don't touch the remote record
    assert git_event_remote_values({"op": "commit", "ok": True}) is None


def test_resolve_git_push_skips_key_load_for_disabled_or_missing() -> None:
    from control_plane.routers.tasks import resolve_git_push

    def explode() -> bytes:
        raise AssertionError("key_loader must not be called")

    # No remote / disabled remote: the master key is never loaded, so keyless
    # flows keep working without CREDENTIAL_ENCRYPTION_KEY.
    assert resolve_git_push(None, explode) is None
    assert resolve_git_push(_remote_row(enabled=False), explode) is None


def test_resolve_git_push_degrades_when_key_unavailable() -> None:
    from control_plane.routers.tasks import resolve_git_push

    def missing() -> bytes:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not set")

    # Enabled remote but no usable key: submission must not blow up — the
    # task proceeds without auto-push.
    assert resolve_git_push(_remote_row(), missing) is None


def test_resolve_git_push_happy_path() -> None:
    from control_plane.routers.tasks import resolve_git_push

    gp = resolve_git_push(_remote_row(), lambda: KEY)
    assert gp is not None and gp.ssh_private_key == _FAKE_PRIVATE_KEY

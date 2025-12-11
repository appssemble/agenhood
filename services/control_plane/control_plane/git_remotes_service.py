"""Pure helpers for per-container git remotes (workspace git rollback spec).

The SSH private (deploy) key follows the same rules as LLM credentials:
AES-GCM ciphertext at rest, decrypted in memory only, never logged, never in
any GET response. Only the public key + fingerprint are ever returned.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_plane.auth.crypto import decrypt_secret, encrypt_secret

# scp-like:  [user@]host:path     (host has no slash; path may be empty — checked below)
_SCP_RE = re.compile(r"^(?P<user>[^@/]+@)?(?P<host>[^/:]+):(?P<path>.*)$")

# Strict hostname charset: alphanumeric, dots, hyphens only.
# Prevents shell metacharacters from reaching build_ssh_command's ProxyCommand.
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+$")

# git check-ref-format rules, reduced to a single branch component.
_BRANCH_BAD = re.compile(r"[ \x00-\x1f\x7f~^:?*\[\\]|\.\.|@\{|//")


def validate_branch(branch: str) -> str:
    """Validate a single branch name per git check-ref-format. Returns it."""
    b = branch.strip()
    if not b or b == "@":
        raise ValueError("branch name is required")
    if b.startswith("/") or b.endswith("/") or b.endswith(".") or b.endswith(".lock"):
        raise ValueError("invalid branch name")
    if _BRANCH_BAD.search(b):
        raise ValueError("invalid branch name")
    if len(b) > 255:
        raise ValueError("branch name too long")
    return b


def validate_remote_url(url: str) -> str:
    """SSH-only. Accept scp-like (git@host:owner/repo) and ssh:// forms.

    Reject http(s), embedded passwords, and missing host/path. Returns the
    trimmed URL.
    """
    url = url.strip()
    if not url:
        raise ValueError("remote URL must be an ssh URL")
    if url.startswith(("http://", "https://")):
        raise ValueError("remote URL must be ssh, not http(s)")
    if "://" in url and not url.startswith("ssh://"):
        raise ValueError("remote URL must be an ssh URL")
    if url.startswith("ssh://"):
        rest = url[len("ssh://"):]
        authority = rest.split("/", 1)[0]
        userinfo = authority.rsplit("@", 1)[0] if "@" in authority else ""
        if userinfo and ":" in userinfo:  # user:password@…
            raise ValueError("remote URL must not embed a password")
        host_port, slash, path = rest.partition("/")
        host = host_port.rsplit("@", 1)[-1].split(":", 1)[0]
        if not host:
            raise ValueError("remote URL has no host")
        if not _HOST_RE.match(host):
            raise ValueError("remote URL host has invalid characters")
        if not slash or not path:
            raise ValueError("remote URL has no repository path")
        return url
    m = _SCP_RE.match(url)
    if not m:
        raise ValueError("remote URL must be an ssh URL (git@host:owner/repo)")
    if ":" in (m.group("user") or "").rstrip("@"):
        raise ValueError("remote URL must not embed a password")
    if not m.group("host"):
        raise ValueError("remote URL has no host")
    if not _HOST_RE.match(m.group("host")):
        raise ValueError("remote URL host has invalid characters")
    if not m.group("path").strip():
        raise ValueError("remote URL has no repository path")
    return url


def remote_host(url: str) -> str:
    """Extract the hostname from a validated ssh URL (used for ProxyCommand)."""
    url = url.strip()
    if url.startswith("ssh://"):
        rest = url[len("ssh://"):]
        authority = rest.split("/", 1)[0]
        return authority.rsplit("@", 1)[-1].split(":", 1)[0]
    m = _SCP_RE.match(url)
    return m.group("host") if m else ""


def build_remote_row(
    *,
    container_id: str,
    url: str,
    branch: str,
    keypair: DeployKey,
    enabled: bool,
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
        "enabled": enabled,
        "created_at": now,
        "updated_at": now,
    }


def decrypt_private_key(row: dict[str, Any], master_key: bytes) -> str:
    return decrypt_secret(row["ssh_private_key_ciphertext"], master_key)


def public_remote_view(row: dict[str, Any]) -> dict[str, Any]:
    """What GET /git/remote returns — never the private key or ciphertext."""
    last_push_at = row.get("last_push_at")
    verified_at = row.get("verified_at")
    return {
        "url": row["url"],
        "branch": row["branch"],
        "ssh_public_key": row.get("ssh_public_key"),
        "key_fingerprint": row.get("key_fingerprint"),
        "key_type": row.get("key_type"),
        "enabled": row["enabled"],
        "verified_at": verified_at.isoformat() if verified_at else None,
        "needs_relink": row.get("ssh_public_key") is None,
        "last_push_status": row.get("last_push_status"),
        "last_push_error": row.get("last_push_error"),
        "last_push_at": last_push_at.isoformat() if last_push_at else None,
    }


@dataclass(frozen=True)
class DeployKey:
    private_key: str  # OpenSSH PEM (stored encrypted)
    public_key: str  # "ssh-ed25519 AAAA… agenhood"
    key_type: str  # "ed25519"
    fingerprint: str  # "SHA256:…"


def _ssh_fingerprint(public_openssh: str) -> str:
    """SHA256 fingerprint of an OpenSSH public key line (ssh-keygen -lf format)."""
    b64 = public_openssh.split()[1]
    digest = hashlib.sha256(base64.b64decode(b64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def generate_deploy_key(comment: str = "agenhood") -> DeployKey:
    """Generate an Ed25519 keypair for a deploy key."""
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()
    public = f"{pub_raw} {comment}"
    return DeployKey(
        private_key=priv,
        public_key=public,
        key_type="ed25519",
        fingerprint=_ssh_fingerprint(pub_raw),
    )

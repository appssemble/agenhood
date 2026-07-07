"""fetch_git_skill against a real ssh remote — proves the deploy-key path
end to end: keygen -> authorized_keys -> clone at pinned SHA -> packed bundle.

Fixture mechanics (local sshd, no docker) are adapted from
``services/shim/tests/integration/test_ssh_remote_integration.py``: generate an
Ed25519 deploy keypair via the same ``generate_deploy_key()`` the control plane
uses, start a local OpenSSH server on 127.0.0.1 with that public key as the
sole authorized key, and seed a bare repo over a real ssh push. Copied here
(rather than imported from the shim test tree) because service test trees do
not import across each other.

Gated on ``sshd``, ``ssh``, and ``git`` being present on the host; the
repo-root conftest additionally auto-marks this module ``integration`` ->
``unit`` fallback and skips the whole run when no docker daemon is reachable
(index: integration tests require docker in this repo, even though this
particular fixture itself only needs local sshd).
"""

from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
import time

import pytest

from control_plane.git_remotes_service import generate_deploy_key
from control_plane.skills_fetch import fetch_git_skill, list_branches

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Prerequisite check
# ---------------------------------------------------------------------------

def _prereqs_available() -> bool:
    """True only when sshd, ssh, and git are all on PATH."""
    return all(shutil.which(t) is not None for t in ("sshd", "ssh", "git"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Ask the OS for a free port, then release the socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _git(cwd: str, *args: str, extra_env: dict | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return result.stdout.strip()


def _ssh_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sshd_or_skip():
    """Module-scope guard: skip the whole module if sshd/ssh/git are absent."""
    if not _prereqs_available():
        pytest.skip("sshd / ssh / git not available on this host")


@pytest.fixture(scope="module")
def deploy_keypair(sshd_or_skip):
    """Ed25519 keypair via the same generate_deploy_key() the control plane uses."""
    return generate_deploy_key(comment="test-integration")


@pytest.fixture(scope="module")
def local_sshd(deploy_keypair, tmp_path_factory):
    """Start a local sshd bound to 127.0.0.1 on a random high port.

    Yields ``(port: int, private_key_pem: str)``.

    The server uses the deploy keypair's public key as the sole authorized key,
    so only calls that carry the matching private key authenticate. If sshd
    does not start within 10 s the fixture calls ``pytest.skip``.
    """
    tmp = tmp_path_factory.mktemp("sshd")

    # Host key
    host_key = tmp / "host_key"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(host_key), "-N", "", "-q"],
        check=True,
    )

    # Authorized keys — only the generated deploy public key
    auth_keys = tmp / "authorized_keys"
    auth_keys.write_text(deploy_keypair.public_key + "\n")
    auth_keys.chmod(0o600)

    port = _free_port()
    sshd_config = tmp / "sshd_config"
    sshd_config.write_text(
        "\n".join([
            f"Port {port}",
            "ListenAddress 127.0.0.1",
            f"HostKey {host_key}",
            f"PidFile {tmp / 'sshd.pid'}",
            f"AuthorizedKeysFile {auth_keys}",
            "PasswordAuthentication no",
            "ChallengeResponseAuthentication no",
            "KbdInteractiveAuthentication no",
            "PubkeyAuthentication yes",
            "StrictModes no",
            "UsePAM no",
            "LogLevel QUIET",
        ]) + "\n"
    )

    proc = subprocess.Popen(
        ["/usr/sbin/sshd", "-D", "-f", str(sshd_config)],
        stderr=subprocess.DEVNULL,
    )

    # Poll until the port is accepting connections
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait()
        pytest.skip("local sshd did not start within 10 s")

    yield port, deploy_keypair.private_key

    proc.terminate()
    proc.wait()


@pytest.fixture(scope="module")
def ssh_skill_remote(sshd_or_skip, local_sshd, tmp_path_factory):
    """Bare repo, reachable over the local sshd, holding ``my-skill/SKILL.md``
    on ``main``. Yields ``(ssh_url, private_key)``."""
    port, private_key = local_sshd

    tmp = tmp_path_factory.mktemp("skill_repo")
    bare = tmp / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True, capture_output=True,
    )

    work = tmp / "work"
    (work / "my-skill").mkdir(parents=True)
    (work / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: test skill\n---\nHello from my-skill.\n"
    )
    git_env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test",
        "GIT_TERMINAL_PROMPT": "0",
    }
    _git(str(work), "init", "-b", "main", extra_env=git_env)
    _git(str(work), "config", "user.name", "Test", extra_env=git_env)
    _git(str(work), "config", "user.email", "test@test", extra_env=git_env)
    _git(str(work), "add", "-A", extra_env=git_env)
    _git(str(work), "commit", "-m", "seed my-skill", extra_env=git_env)
    _git(str(work), "remote", "add", "origin", str(bare), extra_env=git_env)
    _git(str(work), "push", "origin", "main", extra_env=git_env)

    # bare starts with "/" -> double-slash in the URL = absolute path
    url = f"ssh://{_ssh_user()}@127.0.0.1:{port}/{bare}"
    return url, private_key


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_private_skill_fetch_over_ssh(ssh_skill_remote, monkeypatch):
    for var in ("EGRESS_SSH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)

    url, private_key = ssh_skill_remote
    branches, default = list_branches(url, private_key=private_key)
    assert "main" in branches

    fetched = fetch_git_skill(
        url=url, subpath="my-skill", ref="main", private_key=private_key
    )
    assert fetched.name == "my-skill"
    assert fetched.description == "test skill"
    assert len(fetched.pinned_sha) == 40
    assert fetched.bundle  # packed gzip-tar bytes


def test_wrong_key_is_auth_failed(ssh_skill_remote, monkeypatch):
    for var in ("EGRESS_SSH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)

    url, _private_key = ssh_skill_remote
    other = generate_deploy_key().private_key
    with pytest.raises(ValueError, match=r"^auth_failed: "):
        list_branches(url, private_key=other)

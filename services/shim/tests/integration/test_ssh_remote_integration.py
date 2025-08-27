"""Integration test: SSH git operations (ls-remote / push) against a local sshd.

Gated on ``sshd``, ``ssh``, and ``git`` being present on the host; skips
cleanly when any prerequisite is missing (common in minimal CI images).

Design:
    1. Generate an Ed25519 deploy keypair (same call the control plane makes).
    2. Stand up a local OpenSSH server on a random high port (127.0.0.1) with
       the deploy public key as the sole authorized key and ``StrictModes no``
       so temp-dir files pass permission checks.
    3. Build a bare repo with ``main`` (default) + ``dev`` branches.
    4. Exercise ``GitOps.ls_remote()`` and ``GitOps.push()`` over the real SSH
       tunnel — no proxy (``proxy_authority()`` returns None when no proxy env
       vars are set), so ``GIT_SSH_COMMAND`` uses a direct ssh invocation.
"""

from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
import time

import pytest

from shim.git_ops import GitOps

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


def _make_empty_bare_repo(path: str) -> str:
    """Create a bare git repo at *path* and return the path."""
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", path],
        check=True, capture_output=True,
    )
    return path


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
    from control_plane.git_remotes_service import generate_deploy_key

    return generate_deploy_key(comment="test-integration")


@pytest.fixture(scope="module")
def local_sshd(deploy_keypair, tmp_path_factory):
    """Start a local sshd bound to 127.0.0.1 on a random high port.

    Yields ``(port: int, private_key_pem: str)``.

    The server uses the deploy keypair's public key as the sole authorized key,
    so only ``GitOps`` calls that carry the matching private key authenticate.
    If sshd does not start within 10 s the fixture calls ``pytest.skip``.
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
def bare_repo_main_dev(sshd_or_skip, tmp_path_factory):
    """Bare repo with ``main`` (default) and ``dev`` branches."""
    tmp = tmp_path_factory.mktemp("repos")
    bare = tmp / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True, capture_output=True,
    )

    work = tmp / "work"
    work.mkdir()
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
    (work / "README.txt").write_text("hello")
    _git(str(work), "add", "-A", extra_env=git_env)
    _git(str(work), "commit", "-m", "init", extra_env=git_env)
    _git(str(work), "branch", "dev", extra_env=git_env)
    _git(str(work), "remote", "add", "origin", str(bare), extra_env=git_env)
    _git(str(work), "push", "origin", "main", "dev", extra_env=git_env)

    return str(bare)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ssh_ls_remote_lists_branches_and_default(
    monkeypatch,
    local_sshd,
    bare_repo_main_dev,
    tmp_path,
):
    """GitOps.ls_remote() over a live SSH connection returns {main, dev} / default=main.

    Proxy env vars are cleared so proxy_authority() returns None and
    build_ssh_command omits ProxyCommand (direct TCP to 127.0.0.1).
    """
    for var in ("EGRESS_SSH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)

    port, private_key = local_sshd
    # str(bare) starts with "/" so the f-string produces ssh://user@host:port//abs/path
    url = f"ssh://{_ssh_user()}@127.0.0.1:{port}/{bare_repo_main_dev}"

    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    ops = GitOps(ws)

    result = await ops.ls_remote(url=url, ssh_private_key=private_key)

    assert set(result["branches"]) == {"main", "dev"}
    assert result["default_branch"] == "main"


async def test_ssh_verify_remote_returns_branch_dict(
    monkeypatch,
    local_sshd,
    bare_repo_main_dev,
    tmp_path,
):
    """verify_remote() is an alias for ls_remote() — same assertions."""
    for var in ("EGRESS_SSH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)

    port, private_key = local_sshd
    url = f"ssh://{_ssh_user()}@127.0.0.1:{port}/{bare_repo_main_dev}"

    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    ops = GitOps(ws)

    result = await ops.verify_remote(url=url, ssh_private_key=private_key)

    assert "branches" in result
    assert "default_branch" in result
    assert set(result["branches"]) >= {"main", "dev"}


async def test_ssh_push_lands_ref_in_bare_repo(
    monkeypatch,
    local_sshd,
    tmp_path,
):
    """GitOps.push() over SSH advances the remote ref in a fresh empty bare repo."""
    for var in ("EGRESS_SSH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)

    port, private_key = local_sshd

    # Fresh empty bare repo so push is always a fast-forward (no rejection).
    # _make_empty_bare_repo is a sync helper; calling it here avoids an ASYNC221
    # violation (subprocess.run directly in an async function).
    bare = _make_empty_bare_repo(str(tmp_path / "push_remote.git"))
    # bare starts with "/" → double-slash in the URL = absolute path
    url = f"ssh://{_ssh_user()}@127.0.0.1:{port}/{bare}"

    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    ops = GitOps(ws)

    # Build a local commit
    await ops.ensure_repo()
    (tmp_path / "ws" / "output.txt").write_text("task result")
    sha = await ops.commit_all("task tsk_ssh_int: done")
    assert sha is not None

    # Push over SSH
    pushed = await ops.push(url=url, ssh_private_key=private_key, branch="main")
    assert pushed == sha

    # Confirm the ref landed in the bare repo
    remote_sha = _git(str(bare), "rev-parse", "main")
    assert remote_sha == sha

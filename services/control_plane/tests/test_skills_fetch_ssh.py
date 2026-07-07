"""ssh (deploy-key) fetch path: URL rules, GIT_SSH_COMMAND env, key hygiene."""
import os
import stat

import pytest

from control_plane import skills_fetch
from control_plane.skills_fetch import _validate_url, list_branches

pytestmark = pytest.mark.unit

_FAKE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"


def test_https_still_required_without_key():
    with pytest.raises(ValueError, match="https"):
        _validate_url("git@github.com:org/repo.git", has_key=False)


def test_ssh_required_with_key():
    with pytest.raises(ValueError, match="ssh"):
        _validate_url("https://github.com/org/repo", has_key=True)
    _validate_url("git@github.com:org/repo.git", has_key=True)  # no raise


def test_git_env_injects_ssh_command_and_0600_key(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run(args, cwd=None, env=None):
        captured["env"] = env
        return "abc\trefs/heads/main"

    monkeypatch.setattr(skills_fetch, "_run_git", fake_run)
    list_branches("git@github.com:org/repo.git", private_key=_FAKE_KEY)
    ssh_cmd = captured["env"]["GIT_SSH_COMMAND"]
    assert "IdentitiesOnly=yes" in ssh_cmd and "BatchMode=yes" in ssh_cmd
    key_path = ssh_cmd.split(" -i ", 1)[1].split(" ", 1)[0]
    # the key file lives in an ephemeral dir; by the time the call returned it
    # must already be gone
    assert not os.path.exists(key_path)


def test_key_file_mode_is_0600(monkeypatch):
    modes: list[int] = []

    def fake_run(args, cwd=None, env=None):
        ssh_cmd = env["GIT_SSH_COMMAND"]
        key_path = ssh_cmd.split(" -i ", 1)[1].split(" ", 1)[0]
        modes.append(stat.S_IMODE(os.stat(key_path).st_mode))
        return "abc\trefs/heads/main"

    monkeypatch.setattr(skills_fetch, "_run_git", fake_run)
    list_branches("git@github.com:org/repo.git", private_key=_FAKE_KEY)
    assert modes == [0o600]


def test_auth_error_gets_stable_code(monkeypatch):
    def fake_run(args, cwd=None, env=None):
        raise ValueError("git ls-remote failed: Permission denied (publickey).")

    monkeypatch.setattr(skills_fetch, "_run_git", fake_run)
    with pytest.raises(ValueError, match=r"^auth_failed: "):
        list_branches("git@github.com:org/repo.git", private_key=_FAKE_KEY)

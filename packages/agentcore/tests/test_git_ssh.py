"""Shared ssh-command builder + git stderr classifier (moved from the shim)."""
import pytest

from agentcore.git_ssh import build_ssh_command, classify_remote_error

pytestmark = pytest.mark.unit


def test_build_ssh_command_no_proxy():
    cmd = build_ssh_command(
        key_path="/tmp/k", known_hosts="/tmp/kh", host="github.com", proxy=None
    )
    assert cmd.startswith("ssh -i /tmp/k ")
    assert "-o IdentitiesOnly=yes" in cmd
    assert "-o BatchMode=yes" in cmd
    assert "-o StrictHostKeyChecking=accept-new" in cmd
    assert "-o UserKnownHostsFile=/tmp/kh" in cmd
    assert "ProxyCommand" not in cmd


def test_build_ssh_command_with_proxy():
    cmd = build_ssh_command(
        key_path="/k", known_hosts="/kh", host="github.com", proxy="proxy:3128"
    )
    assert 'ProxyCommand="nc -X connect -x proxy:3128 github.com 22"' in cmd


def test_build_ssh_command_rejects_bad_host():
    with pytest.raises(ValueError):
        build_ssh_command(key_path="/k", known_hosts="/kh", host="evil;rm -rf", proxy=None)


@pytest.mark.parametrize(
    "stderr,code",
    [
        ("Permission denied (publickey)", "auth_failed"),
        ("ERROR: Repository not found.", "repo_not_found"),
        ("ssh: Could not resolve host github.com", "host_unreachable"),
        ("Host key verification failed.", "host_key_changed"),
        ("something inscrutable", "push_failed"),
    ],
)
def test_classify_remote_error(stderr, code):
    assert classify_remote_error(stderr) == code

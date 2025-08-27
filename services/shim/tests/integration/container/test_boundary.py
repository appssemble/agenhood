# services/shim/tests/integration/container/test_boundary.py
#
# Privilege-separation boundary tests (spec §8.3).
# All checks run as uid 1000:1000 inside the LIVE agent container, simulating
# an untrusted leaf process spawned by the shim.  The shim runs as root
# (PID 1 under tini); the agent uid must not be able to read shim secrets,
# rename private dirs, or signal PID 1.
#
# LIFTED from: services/shim/tests/integration/test_container_e2e.py
#   test_agent_uid_cannot_breach_shim (6 checks → 8 standalone tests here)
# EXTENDED with:
#   test_shim_token_not_in_pid1_cmdline  — second attack vector for token leak
#   test_agent_can_write_workspace_but_not_runtime — positive + negative write
#   test_git_safe_directory_configured   — workspace git safety (new)
import subprocess

import pytest

pytestmark = pytest.mark.integration


def _as_agent(compose, cmd):
    result = subprocess.run(
        compose + ["exec", "-T", "-u", "1000:1000", "agent", "sh", "-c", cmd],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Token-leak checks (two attack vectors)
# ---------------------------------------------------------------------------

def test_shim_token_not_in_pid1_environ(stack):
    """SHIM_TOKEN must not be readable from /proc/1/environ by unprivileged uid."""
    rc, out = _as_agent(
        stack, 'cat /proc/1/environ | tr "\\0" "\\n" | grep SHIM_TOKEN || echo NOPE')
    assert "test-shim-token" not in out and "NOPE" in out, out


def test_shim_token_not_in_pid1_cmdline(stack):
    """SHIM_TOKEN must not appear as a --token flag on PID 1's cmdline.

    Lifted from legacy test_agent_uid_cannot_breach_shim check #2.
    The shim reads SHIM_TOKEN from the environment, never passing it as a
    positional argument; this test confirms the cmdline is unpolluted.
    """
    rc, out = _as_agent(stack, "cat /proc/1/cmdline | tr '\\0' ' '")
    assert rc == 0, f"could not read /proc/1/cmdline; output={out!r}"
    assert "--token" not in out, (
        f"--token flag found on PID 1 cmdline; output={out!r}"
    )


# ---------------------------------------------------------------------------
# Shim-private directory access
# ---------------------------------------------------------------------------

def test_agent_runtime_unreadable(stack):
    """.agent-runtime dir must be unreadable to uid 1000."""
    # as root, confirm the dir exists first (else the denial below is vacuous)
    root = subprocess.run(
        stack + ["exec", "-T", "-u", "0:0", "agent", "sh", "-c",
                 "test -d /workspace/.agent-runtime && echo OK"],
        capture_output=True, text=True,
    )
    assert "OK" in root.stdout, (
        ".agent-runtime not present as root — test would be vacuous"
    )
    rc, out = _as_agent(stack, "ls /workspace/.agent-runtime 2>&1")
    assert rc != 0, out


def test_agent_cannot_rename_runtime(stack):
    """Agent uid must not rename/unlink the shim-private dir."""
    # as root, confirm the dir exists first (else the denial below is vacuous)
    root = subprocess.run(
        stack + ["exec", "-T", "-u", "0:0", "agent", "sh", "-c",
                 "test -d /workspace/.agent-runtime && echo OK"],
        capture_output=True, text=True,
    )
    assert "OK" in root.stdout, (
        ".agent-runtime not present as root — test would be vacuous"
    )
    rc, out = _as_agent(stack, "mv /workspace/.agent-runtime /workspace/.evil 2>&1")
    assert rc != 0, out


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------

def test_agent_cannot_kill_pid1(stack):
    """Agent uid must not be able to signal the shim process."""
    rc, out = _as_agent(stack, "kill -9 1 2>&1")
    assert rc != 0, out


# ---------------------------------------------------------------------------
# uid sanity
# ---------------------------------------------------------------------------

def test_agent_uid_is_1000(stack):
    """Confirm the effective uid inside the container is unprivileged (1000)."""
    rc, out = _as_agent(stack, "id -u")
    assert out.strip() == "1000", out


# ---------------------------------------------------------------------------
# Workspace write permissions (positive + negative)
# ---------------------------------------------------------------------------

def test_agent_can_write_workspace_but_not_runtime(stack):
    """Agent uid can write to /workspace but not into the shim-private subdir."""
    rc, _ = _as_agent(stack, "echo ok > /workspace/agent_write.txt")
    assert rc == 0
    rc, _ = _as_agent(stack, "echo evil > /workspace/.agent-runtime/x 2>&1")
    assert rc != 0


# ---------------------------------------------------------------------------
# Git safe-directory (extended check — new in this suite)
# ---------------------------------------------------------------------------

def test_git_safe_directory_configured(stack):
    """git must consider /workspace safe for the agent uid (no dubious-owner error)."""
    rc, out = _as_agent(
        stack, "git config --system --get-all safe.directory 2>&1")
    assert "/workspace" in out, out

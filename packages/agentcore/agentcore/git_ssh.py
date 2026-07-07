"""Hardened GIT_SSH_COMMAND builder + git stderr → stable-error-code mapping.

Shared by the shim (which tunnels through the egress proxy) and the control
plane (direct internet, no proxy). Moved from services/shim/shim/git_ops.py.
"""
from __future__ import annotations

import re

# Strict hostname charset: alphanumeric, dots, hyphens only.
# Prevents shell metacharacters from reaching the ProxyCommand.
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+$")


def build_ssh_command(
    *, key_path: str, known_hosts: str, host: str, proxy: str | None = None,
) -> str:
    """The GIT_SSH_COMMAND value: identity-only ssh, host-key TOFU, optional
    proxy tunnel via the egress proxy's CONNECT verb."""
    if host and not _HOST_RE.match(host):
        raise ValueError("invalid ssh host")
    parts = [
        "ssh", "-i", key_path,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
        f"-o UserKnownHostsFile={known_hosts}",
    ]
    if proxy:
        parts += ["-o", f'ProxyCommand="nc -X connect -x {proxy} {host} 22"']
    return " ".join(parts)


def classify_remote_error(stderr: str) -> str:
    """Map git remote operation stderr to a stable error code."""
    s = stderr.lower()
    if ("permission denied" in s or "authentication failed" in s
            or "publickey" in s or "access denied" in s):
        return "auth_failed"
    if "host key verification failed" in s or "remote host identification" in s:
        return "host_key_changed"
    if ("could not resolve host" in s or "name or service not known" in s
            or "connection" in s or "timed out" in s or "unable to access" in s):
        return "host_unreachable"
    if "repository not found" in s or "does not exist" in s:
        return "repo_not_found"
    if "[rejected]" in s or "non-fast-forward" in s or "fetch first" in s:
        return "push_rejected"
    if "403" in s or "blocked" in s:
        return "egress_blocked"
    return "push_failed"

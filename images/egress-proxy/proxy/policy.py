"""Pure egress policy classifier for the filtering forward proxy.

Block: RFC1918 private ranges, link-local (169.254/16, incl. cloud metadata),
loopback, and a configurable denylist of hostnames. Allow everything else.
Hostnames are resolved; if ANY resolved IP is in a blocked range the host is
blocked (DNS-rebinding defence). The resolver is injected so this stays a pure,
offline-testable function.
"""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass

Resolver = Callable[[str], "list[str]"]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # "allowed" | "private_range" | "link_local" | "loopback"
                 # | "denylisted" | "dns_failure"


@dataclass(frozen=True)
class EgressPolicy:
    denylist: frozenset[str]  # lowercased hostnames

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> EgressPolicy:
        raw = env.get("EGRESS_DENYLIST", "")
        hosts = frozenset(
            h.strip().lower() for h in raw.split(",") if h.strip()
        )
        return cls(denylist=hosts)


def _system_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


def _ip_reason(ip_str: str) -> str | None:
    """Return a block reason for an IP literal, or None if it is allowed."""
    ip = ipaddress.ip_address(ip_str)
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:  # 169.254.0.0/16 and fe80::/10 — covers metadata endpoint
        return "link_local"
    if ip.is_private:     # 10/8, 172.16/12, 192.168/16, fc00::/7, etc.
        return "private_range"
    return None


def classify(host: str, policy: EgressPolicy, *, resolve: Resolver = _system_resolve) -> Decision:
    host_lc = host.lower()
    if host_lc in policy.denylist:
        return Decision(allowed=False, reason="denylisted")

    # If the host is already an IP literal, classify it directly.
    try:
        ipaddress.ip_address(host)
        reason = _ip_reason(host)
        if reason is not None:
            return Decision(allowed=False, reason=reason)
        return Decision(allowed=True, reason="allowed")
    except ValueError:
        pass  # not an IP literal — resolve it

    try:
        ips = resolve(host)
    except OSError:
        return Decision(allowed=False, reason="dns_failure")
    if not ips:
        return Decision(allowed=False, reason="dns_failure")

    for ip_str in ips:
        reason = _ip_reason(ip_str)
        if reason is not None:
            return Decision(allowed=False, reason=reason)
    return Decision(allowed=True, reason="allowed")

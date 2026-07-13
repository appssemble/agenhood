"""Pure egress policy classifier for the filtering forward proxy.

Block: RFC1918 private ranges, link-local (169.254/16, incl. cloud metadata),
loopback, and a configurable denylist of hostnames. Allow everything else.
Hostnames are resolved; if ANY resolved IP is in a blocked range the host is
blocked (DNS-rebinding defence). The resolver is injected so this stays a pure,
offline-testable function.

``UpstreamPolicy`` is the separate, orthogonal question of *how* an already-allowed
host is reached: directly, or chained through an upstream proxy (e.g. a rotating
service such as Webshare). Allow/block always decides first; routing never
overrides it.
"""
from __future__ import annotations

import base64
import ipaddress
import socket
import urllib.parse
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


def _host_list(raw: str) -> frozenset[str]:
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def _env_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class UpstreamPolicy:
    """Where an allowed request is sent: direct, or via an upstream proxy.

    ``mode`` is one of:
      * "all"     — no list configured; every allowed host chains upstream.
      * "exclude" — listed hosts go direct, everything else chains (blacklist).
      * "include" — listed hosts chain, everything else goes direct (whitelist).

    ``from_env`` returns None when no upstream is configured, so "feature off" is
    a single unambiguous state at the call sites.
    """

    host: str
    port: int
    username: str | None
    password: str | None
    mode: str
    hosts: frozenset[str]  # lowercased; meaning depends on mode
    # When the upstream is unreachable, fall back to a direct origin connection
    # instead of failing the request with 502. OFF by default: a direct fallback
    # leaks this VM's real IP, so an operator must opt in explicitly.
    fallback_direct: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> UpstreamPolicy | None:
        url = env.get("EGRESS_UPSTREAM_PROXY", "").strip()
        exclude = _host_list(env.get("EGRESS_UPSTREAM_EXCLUDE", ""))
        include = _host_list(env.get("EGRESS_UPSTREAM_INCLUDE", ""))

        if exclude and include:
            raise ValueError(
                "EGRESS_UPSTREAM_EXCLUDE and EGRESS_UPSTREAM_INCLUDE are mutually "
                "exclusive: set one (blacklist) or the other (whitelist), not both"
            )
        if not url:
            if exclude or include:
                # Silently ignoring the lists would hide a misconfiguration that
                # sends every request direct — fail fast instead.
                raise ValueError(
                    "EGRESS_UPSTREAM_EXCLUDE/EGRESS_UPSTREAM_INCLUDE set without "
                    "EGRESS_UPSTREAM_PROXY"
                )
            return None

        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError(
                f"EGRESS_UPSTREAM_PROXY must be http://[user:pass@]host[:port], got {url!r}"
            )
        return cls(
            host=parsed.hostname,
            port=parsed.port or 80,
            username=urllib.parse.unquote(parsed.username) if parsed.username else None,
            password=urllib.parse.unquote(parsed.password) if parsed.password else None,
            mode="exclude" if exclude else "include" if include else "all",
            hosts=exclude or include,
            fallback_direct=_env_bool(env.get("EGRESS_UPSTREAM_FALLBACK_DIRECT", "")),
        )

    def proxy_authorization(self) -> str | None:
        """The Proxy-Authorization header value, or None when unauthenticated."""
        if self.username is None:
            return None
        raw = f"{self.username}:{self.password or ''}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def route(self, host: str) -> bool:
        """True if this (already-allowed) host should chain through the upstream."""
        if self.mode == "all":
            return True
        listed = _matches(host, self.hosts)
        return not listed if self.mode == "exclude" else listed


def _matches(host: str, hosts: frozenset[str]) -> bool:
    """NO_PROXY-style suffix match: an entry matches the host itself and any
    subdomain of it, on label boundaries ("example.com" does not match
    "notexample.com")."""
    host_lc = host.lower().rstrip(".")
    return any(
        host_lc == entry or host_lc.endswith("." + entry)
        for entry in hosts
    )


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

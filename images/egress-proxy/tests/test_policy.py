import pytest
from proxy.policy import Decision, EgressPolicy, classify


def fake_resolver(mapping):
    """Return a resolver func that maps hostname -> list[str] of IPs."""
    def _resolve(host: str) -> list[str]:
        if host in mapping:
            return mapping[host]
        raise OSError(f"no fake DNS entry for {host}")
    return _resolve


def test_allows_public_ip_literal():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("93.184.216.34", policy, resolve=fake_resolver({}))
    assert d == Decision(allowed=True, reason="allowed")


def test_allows_public_hostname():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("example.com", policy,
                 resolve=fake_resolver({"example.com": ["93.184.216.34"]}))
    assert d.allowed is True
    assert d.reason == "allowed"


def test_blocks_rfc1918_10_8():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("10.1.2.3", policy, resolve=fake_resolver({}))
    assert d == Decision(allowed=False, reason="private_range")


def test_blocks_rfc1918_192_168():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("192.168.0.5", policy, resolve=fake_resolver({}))
    assert d.allowed is False
    assert d.reason == "private_range"


def test_172_15_is_public_but_172_16_is_private_boundary():
    policy = EgressPolicy(denylist=frozenset())
    allowed = classify("172.15.255.255", policy, resolve=fake_resolver({}))
    blocked = classify("172.16.0.0", policy, resolve=fake_resolver({}))
    assert allowed.allowed is True
    assert blocked.allowed is False and blocked.reason == "private_range"


def test_172_31_blocked_172_32_allowed_boundary():
    policy = EgressPolicy(denylist=frozenset())
    blocked = classify("172.31.255.255", policy, resolve=fake_resolver({}))
    allowed = classify("172.32.0.0", policy, resolve=fake_resolver({}))
    assert blocked.allowed is False and blocked.reason == "private_range"
    assert allowed.allowed is True


def test_blocks_link_local_metadata_endpoint():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("169.254.169.254", policy, resolve=fake_resolver({}))
    assert d == Decision(allowed=False, reason="link_local")


def test_blocks_loopback():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("127.0.0.1", policy, resolve=fake_resolver({}))
    assert d.allowed is False and d.reason == "loopback"


def test_blocks_hostname_that_resolves_into_private_range():
    # DNS-rebinding defence: a public-looking name pointing at a private IP.
    policy = EgressPolicy(denylist=frozenset())
    d = classify("evil.example.com", policy,
                 resolve=fake_resolver({"evil.example.com": ["169.254.169.254"]}))
    assert d.allowed is False and d.reason == "link_local"


def test_blocks_if_any_resolved_ip_is_private():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("mixed.example.com", policy,
                 resolve=fake_resolver({"mixed.example.com": ["93.184.216.34", "10.0.0.1"]}))
    assert d.allowed is False and d.reason == "private_range"


def test_blocks_denylisted_host_before_resolving():
    policy = EgressPolicy(denylist=frozenset({"ads.tracker.example"}))
    d = classify("ads.tracker.example", policy, resolve=fake_resolver({}))
    assert d == Decision(allowed=False, reason="denylisted")


def test_denylist_is_case_insensitive():
    policy = EgressPolicy(denylist=frozenset({"ads.tracker.example"}))
    d = classify("ADS.Tracker.Example", policy, resolve=fake_resolver({}))
    assert d.allowed is False and d.reason == "denylisted"


def test_unresolvable_host_is_blocked():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("does-not-exist.invalid", policy, resolve=fake_resolver({}))
    assert d.allowed is False and d.reason == "dns_failure"


def test_policy_from_env_parses_comma_separated_denylist():
    policy = EgressPolicy.from_env({"EGRESS_DENYLIST": "a.example, b.example ,C.EXAMPLE"})
    assert policy.denylist == frozenset({"a.example", "b.example", "c.example"})


def test_policy_from_env_empty_denylist():
    policy = EgressPolicy.from_env({})
    assert policy.denylist == frozenset()


def test_empty_resolution_is_dns_failure():
    # Distinct from the OSError path: resolver returns an EMPTY list (line 76).
    policy = EgressPolicy(denylist=frozenset())
    d = classify("ghost.example", policy, resolve=lambda _host: [])
    assert d == Decision(allowed=False, reason="dns_failure")


@pytest.mark.parametrize(
    "ip, reason",
    [
        ("::1", "loopback"),           # IPv6 loopback
        ("fe80::1", "link_local"),     # IPv6 link-local
        ("fc00::1", "private_range"),  # IPv6 ULA (fc00::/7)
    ],
)
def test_blocks_ipv6_private_ranges(ip, reason):
    policy = EgressPolicy(denylist=frozenset())
    d = classify(ip, policy, resolve=fake_resolver({}))
    assert d == Decision(allowed=False, reason=reason)


def test_allows_public_ipv6_literal():
    policy = EgressPolicy(denylist=frozenset())
    d = classify("2606:2800:220:1:248:1893:25c8:1946", policy,
                 resolve=fake_resolver({}))
    assert d == Decision(allowed=True, reason="allowed")


def test_default_system_resolver_blocks_localhost():
    # Exercises the real _system_resolve default arg (lines 40-41): localhost
    # resolves to loopback on every dev/CI box → blocked.
    policy = EgressPolicy(denylist=frozenset())
    d = classify("localhost", policy)           # no resolve= → _system_resolve
    assert d.allowed is False and d.reason == "loopback"

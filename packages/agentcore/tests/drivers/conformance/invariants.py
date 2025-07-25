from __future__ import annotations

from typing import Any

from tests.drivers.conformance.fakes import ACCOUNT, CRED, MCP_SECRET, REFRESH

_SECRETS = [CRED, REFRESH, ACCOUNT, MCP_SECRET]
_TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def assert_no_secret_leak(blob: str) -> None:
    for s in _SECRETS:
        assert s not in blob, f"raw secret leaked into output: {s!r}"


def assert_single_terminal_status(events: list[tuple[str, dict[str, Any]]]) -> None:
    n = sum(1 for t, p in events if t == "status_change" and p.get("to") in _TERMINAL)
    assert n == 1, f"expected exactly one terminal status_change, got {n}"


def assert_monotonic_seq(events: list[Any]) -> None:
    seqs = [e[1].get("seq") for e in events if isinstance(e[1], dict) and "seq" in e[1]]
    assert seqs == sorted(set(seqs)), f"event seqs not strictly increasing: {seqs}"

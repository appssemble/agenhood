import json

import pytest

from tests.drivers.conformance import invariants as inv
from tests.drivers.conformance.fakes import ACCOUNT, CRED, MCP_SECRET, REFRESH

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# assert_no_secret_leak
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [CRED, REFRESH, ACCOUNT, MCP_SECRET])
def test_no_secret_leak_detects_raw_secret(secret):
    with pytest.raises(AssertionError):
        inv.assert_no_secret_leak(json.dumps({"k": secret}))


def test_no_secret_leak_passes_when_redacted():
    inv.assert_no_secret_leak(
        json.dumps({"k": "<CRED>", "r": "<REFRESH>", "a": "<ACCOUNT>", "m": "<MCP_SECRET>"})
    )


# ---------------------------------------------------------------------------
# assert_single_terminal_status
# ---------------------------------------------------------------------------


def test_single_terminal_status_rejects_two():
    events = [("status_change", {"to": "completed"}), ("status_change", {"to": "failed"})]
    with pytest.raises(AssertionError):
        inv.assert_single_terminal_status(events)


def test_single_terminal_status_rejects_zero():
    with pytest.raises(AssertionError):
        inv.assert_single_terminal_status([])


def test_single_terminal_status_rejects_zero_with_non_terminal():
    events = [("status_change", {"to": "running"}), ("status_change", {"to": "paused"})]
    with pytest.raises(AssertionError):
        inv.assert_single_terminal_status(events)


def test_single_terminal_status_accepts_one():
    inv.assert_single_terminal_status(
        [("status_change", {"to": "running"}), ("status_change", {"to": "completed"})]
    )


# ---------------------------------------------------------------------------
# assert_monotonic_seq
# ---------------------------------------------------------------------------


def test_monotonic_seq_pass():
    events = [("e", {"seq": 1}), ("e", {"seq": 2}), ("e", {"seq": 3})]
    inv.assert_monotonic_seq(events)


def test_monotonic_seq_noop_when_absent():
    events = [("status_change", {"to": "completed"})]
    inv.assert_monotonic_seq(events)


def test_monotonic_seq_raises_on_out_of_order():
    events = [("e", {"seq": 3}), ("e", {"seq": 1})]
    with pytest.raises(AssertionError):
        inv.assert_monotonic_seq(events)

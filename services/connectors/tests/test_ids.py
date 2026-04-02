import re

import pytest

from connectors.ids import new_id, ulid

pytestmark = pytest.mark.unit


def test_ulid_is_26_crockford_chars():
    u = ulid()
    assert len(u) == 26
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", u)


def test_new_id_has_prefix_and_is_unique():
    a = new_id("con")
    b = new_id("con")
    assert a.startswith("con_") and b.startswith("con_")
    assert a != b

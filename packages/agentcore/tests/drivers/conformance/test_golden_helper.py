from __future__ import annotations

import dataclasses

import pytest

from tests.drivers.conformance.golden_helper import golden, to_jsonable

pytestmark = pytest.mark.unit


@dataclasses.dataclass(frozen=True)
class _Caps:
    a: bool
    b: str


def test_to_jsonable_handles_dataclass_and_nested():
    out = to_jsonable({"caps": _Caps(a=True, b="x"), "xs": (1, 2)})
    assert out == {"caps": {"a": True, "b": "x"}, "xs": [1, 2]}


def test_missing_golden_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.drivers.conformance.golden_helper._GOLDEN_DIR", tmp_path
    )
    monkeypatch.delenv("UPDATE_GOLDEN", raising=False)
    with pytest.raises(AssertionError):
        golden("nope/missing", {"x": 1})


def test_update_then_match_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.drivers.conformance.golden_helper._GOLDEN_DIR", tmp_path
    )
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    golden("x/case", {"v": 1})                       # writes
    monkeypatch.delenv("UPDATE_GOLDEN", raising=False)
    golden("x/case", {"v": 1})                       # matches → no raise
    with pytest.raises(AssertionError):
        golden("x/case", {"v": 2})                   # differs → diff


def test_subs_redacts_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.drivers.conformance.golden_helper._GOLDEN_DIR", tmp_path
    )
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    golden("s/case", {"token": "supersecret"}, subs={"supersecret": "<CRED>"})
    written = (tmp_path / "s" / "case.json").read_text()
    assert "supersecret" not in written and "<CRED>" in written

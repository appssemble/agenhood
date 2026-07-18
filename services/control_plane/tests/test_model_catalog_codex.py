import pytest

from control_plane.model_catalog import build_catalog_entries

pytestmark = pytest.mark.unit


def test_codex_driver_uses_authoritative_list_not_substring():
    # When an authoritative codex-runnable set is supplied (from `codex debug
    # models`), codex-driver membership comes from THAT set — not the "codex"
    # substring heuristic. This is the fix for the runtime 400 where a model
    # like gpt-5.3-codex (substring match, but unsupported on a ChatGPT account)
    # was wrongly offered for the codex driver.
    base = [
        "openai/gpt-5.3-codex",       # substring would wrongly include this
        "openai/gpt-5.4",             # substring would wrongly exclude this
        "openai/gpt-5.5",             # substring would wrongly exclude this
        "openai/gpt-5.3-codex-spark",
    ]
    codex_ids = ["gpt-5.4", "gpt-5.5", "gpt-5.3-codex-spark"]  # no plain gpt-5.3-codex
    entries = build_catalog_entries(base, [], codex_ids=codex_ids)
    by_id = {e["id"]: e for e in entries}

    assert "codex" not in by_id["gpt-5.3-codex"]["drivers"]
    assert by_id["gpt-5.3-codex"]["drivers"] == ["opencode", "api"]
    for mid in ("gpt-5.4", "gpt-5.5", "gpt-5.3-codex-spark"):
        assert "codex" in by_id[mid]["drivers"]
        assert "opencode" in by_id[mid]["drivers"]


def test_codex_ids_none_falls_back_to_substring():
    # Back-compat: with no authoritative list (codex auth unavailable at build
    # time), the legacy "codex"-substring heuristic still applies.
    entries = build_catalog_entries(
        ["openai/gpt-5-codex", "openai/gpt-5.3-codex-spark", "openai/gpt-4o"], []
    )
    by_id = {e["id"]: e for e in entries}
    for mid in ("gpt-5-codex", "gpt-5.3-codex-spark"):
        assert "codex" in by_id[mid]["drivers"]
        assert "opencode" in by_id[mid]["drivers"]
    assert by_id["gpt-4o"]["drivers"] == ["opencode", "vanilla", "api"]


def test_empty_codex_ids_excludes_all_codex():
    # An explicit empty authoritative list means codex runs nothing (not the
    # same as None, which falls back to substring).
    entries = build_catalog_entries(
        ["openai/gpt-5.3-codex-spark", "openai/gpt-4o"], [], codex_ids=[]
    )
    for e in entries:
        assert "codex" not in e["drivers"]


def test_anthropic_models_do_not_list_codex():
    entries = build_catalog_entries(["anthropic/claude-x"], [])
    claude = next(e for e in entries if e["id"] == "claude-x")
    assert "codex" not in claude["drivers"]


def test_codex_in_default_allowed_drivers():
    from control_plane.tenant_defaults import default_limits

    assert "codex" in default_limits()["allowed_drivers"]

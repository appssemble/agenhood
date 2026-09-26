"""Codex tool toggles in the control plane."""
from __future__ import annotations

import pytest

import agentcore.drivers  # noqa: F401  registers every driver
from agentcore.models import AgentConfig

pytestmark = pytest.mark.unit

CODEX_TOOL_NAMES = ["web_search", "image_generation", "view_image", "multi_agent", "goals"]


def test_template_view_lists_codex_tool_specs():
    from control_plane.routers.templates import template_public_view

    view = template_public_view({"driver": "codex"})
    assert [s["name"] for s in view["available_tool_specs"]] == CODEX_TOOL_NAMES
    assert view["driver_template"]["default_tools"] == ["web_search"]
    assert view["driver_template"]["tools_user_editable"] is True


def test_template_view_vanilla_unchanged():
    from agentcore.drivers.base import DRIVERS
    from control_plane.routers.templates import template_public_view

    view = template_public_view({"driver": "vanilla"})
    names = [s["name"] for s in view["available_tool_specs"]]
    assert names == DRIVERS["vanilla"].default_template.available_tools


def test_seed_codex_builtin_starts_with_web_search_only():
    from control_plane.seed import build_builtin_template_rows

    rows = {r["driver"]: r for r in build_builtin_template_rows()}
    assert rows["codex"]["tools"] == ["web_search"]
    assert rows["claude-code"]["tools"] == []


def test_seed_vanilla_builtin_keeps_all_tools():
    from agentcore.drivers.base import DRIVERS
    from control_plane.seed import build_builtin_template_rows

    rows = {r["driver"]: r for r in build_builtin_template_rows()}
    assert rows["vanilla"]["tools"] == DRIVERS["vanilla"].default_template.available_tools


def test_codex_tools_pass_slim_variant_check():
    from agentcore.drivers.base import DRIVERS
    from agentcore.tools.base import TOOLS
    from control_plane.variants import assert_config_runnable_on_variant

    assert_config_runnable_on_variant(
        variant="slim", driver_name="codex", tool_names=CODEX_TOOL_NAMES,
        drivers=DRIVERS, tools=TOOLS,
    )


def _codex(**kw):
    return AgentConfig(driver="codex", model="gpt-5.4", **kw)


def test_default_tools_for():
    from control_plane.config_validation import default_tools_for

    assert default_tools_for("codex") == ["web_search"]
    assert default_tools_for("vanilla") is None
    assert default_tools_for("nope") is None


def test_fill_default_tools_when_omitted():
    from control_plane.config_validation import fill_default_tools

    assert fill_default_tools(_codex(), tools_given=False).tools == ["web_search"]


def test_fill_default_tools_keeps_explicit_empty():
    from control_plane.config_validation import fill_default_tools

    cfg = _codex(tools=[])
    assert fill_default_tools(cfg, tools_given=True) is cfg


def test_fill_default_tools_leaves_vanilla_empty():
    from control_plane.config_validation import fill_default_tools

    cfg = AgentConfig(driver="vanilla", model="m")
    assert fill_default_tools(cfg, tools_given=False).tools == []


def test_config_patch_without_tools_keeps_web_search():
    from control_plane.config_validation import fill_default_tools
    from control_plane.schemas import ConfigPatch

    patch = ConfigPatch(driver="codex", model="gpt-5.4")
    cfg = fill_default_tools(
        patch.to_agent_config(), tools_given="tools" in patch.model_fields_set
    )
    assert cfg.tools == ["web_search"]


def test_config_patch_with_empty_tools_turns_all_off():
    from control_plane.config_validation import fill_default_tools
    from control_plane.schemas import ConfigPatch

    patch = ConfigPatch(driver="codex", model="gpt-5.4", tools=[])
    cfg = fill_default_tools(
        patch.to_agent_config(), tools_given="tools" in patch.model_fields_set
    )
    assert cfg.tools == []


LIMITS = {"allowed_drivers": ["vanilla", "opencode", "claude-code", "codex"]}


def test_validate_config_accepts_codex_tools():
    from control_plane.config_validation import validate_config

    validate_config(
        AgentConfig(driver="codex", model="gpt-5.5", tools=CODEX_TOOL_NAMES), LIMITS
    )  # must not raise


def test_validate_config_rejects_unknown_codex_tool():
    from control_plane.config_validation import validate_config
    from control_plane.errors import APIError

    with pytest.raises(APIError) as exc:
        validate_config(AgentConfig(driver="codex", model="gpt-5.5", tools=["bash"]), LIMITS)
    assert exc.value.field == "tools"

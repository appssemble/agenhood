"""Codex tool toggles in the control plane."""
from __future__ import annotations

import pytest

import agentcore.drivers  # noqa: F401  registers every driver

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

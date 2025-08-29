from __future__ import annotations

from dataclasses import dataclass

import pytest

from control_plane import variants
from control_plane.errors import Conflict

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class FakeCaps:
    requires_image_feature: str | None = None


@dataclass(frozen=True)
class FakeDriver:
    name: str
    capabilities: FakeCaps


@dataclass(frozen=True)
class FakeToolSpec:
    name: str
    requires_image_feature: str | None = None


@dataclass(frozen=True)
class FakeTool:
    spec: FakeToolSpec


def test_full_variant_provides_chromium() -> None:
    assert "chromium" in variants.image_variant_features("full")


def test_slim_variant_lacks_chromium() -> None:
    assert "chromium" not in variants.image_variant_features("slim")


def test_gate_rejects_chromium_driver_on_slim() -> None:
    drivers = {"render": FakeDriver("render", FakeCaps(requires_image_feature="chromium"))}
    tools: dict = {}
    with pytest.raises(Conflict) as ei:
        variants.assert_config_runnable_on_variant(
            variant="slim",
            driver_name="render",
            tool_names=[],
            drivers=drivers,
            tools=tools,
        )
    assert ei.value.status_code == 409
    assert ei.value.code == "validation_error"
    assert "chromium" in ei.value.message


def test_gate_rejects_chromium_tool_on_slim() -> None:
    drivers = {"vanilla": FakeDriver("vanilla", FakeCaps())}
    tools = {"web_fetch": FakeTool(FakeToolSpec("web_fetch", requires_image_feature="chromium"))}
    with pytest.raises(Conflict):
        variants.assert_config_runnable_on_variant(
            variant="slim",
            driver_name="vanilla",
            tool_names=["web_fetch"],
            drivers=drivers,
            tools=tools,
        )


def test_gate_allows_chromium_tool_on_full() -> None:
    drivers = {"vanilla": FakeDriver("vanilla", FakeCaps())}
    tools = {"web_fetch": FakeTool(FakeToolSpec("web_fetch", requires_image_feature="chromium"))}
    # no raise
    variants.assert_config_runnable_on_variant(
        variant="full",
        driver_name="vanilla",
        tool_names=["web_fetch"],
        drivers=drivers,
        tools=tools,
    )


def test_gate_allows_featureless_config_on_slim() -> None:
    drivers = {"vanilla": FakeDriver("vanilla", FakeCaps())}
    tools = {"read_file": FakeTool(FakeToolSpec("read_file"))}
    variants.assert_config_runnable_on_variant(
        variant="slim",
        driver_name="vanilla",
        tool_names=["read_file"],
        drivers=drivers,
        tools=tools,
    )

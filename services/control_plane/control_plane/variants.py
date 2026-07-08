from __future__ import annotations

from typing import Any

from control_plane.errors import APIError

# Feature sets per image variant (spec §9.1). full ships Chromium; slim omits it.
_VARIANT_FEATURES: dict[str, frozenset[str]] = {
    "full": frozenset({"chromium"}),
    "slim": frozenset(),
}


def image_variant_features(variant: str) -> frozenset[str]:
    return _VARIANT_FEATURES.get(variant, frozenset())


def known_variants() -> frozenset[str]:
    """The image variants that exist (spec §9.1)."""
    return frozenset(_VARIANT_FEATURES)


def assert_config_runnable_on_variant(
    *,
    variant: str,
    driver_name: str,
    tool_names: list[str],
    drivers: dict[str, Any],  # name -> Driver (capabilities.requires_image_feature)
    tools: dict[str, Any],  # name -> Tool (spec.requires_image_feature)
) -> None:
    """Raise validation_error (409) if the driver or any enabled tool needs an image feature
    the variant does not provide (spec §9.1). DRYs the requires_image_feature check across both."""
    have = image_variant_features(variant)

    def _check(label: str, name: str, needed: str | None) -> None:
        if needed and needed not in have:
            raise APIError(
                409,
                "validation_error",
                f"{label} '{name}' requires image feature '{needed}', "
                f"which the '{variant}' image variant does not provide",
                field="image_variant",
            )

    drv = drivers.get(driver_name)
    if drv is not None:
        _check("driver", driver_name, drv.capabilities.requires_image_feature)
    for tname in tool_names:
        tool = tools.get(tname)
        if tool is not None:
            _check("tool", tname, tool.spec.requires_image_feature)

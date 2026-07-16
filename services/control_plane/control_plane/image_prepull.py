"""Background pre-pull of the default agent image (registry mode only).

Keeps ``settings.agent_image_tag`` warm on the Docker host so user-facing
creates are never the thing that downloads the ~1 GB agent image. A failed
pass logs and retries next tick — creates still work through the on-demand
pull path in provision_container.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from control_plane.config import Settings
from control_plane.docker_ctl import provision

log = logging.getLogger("image_prepull")


async def ensure_agent_image(docker_client: Any, settings: Settings) -> None:
    """One pass: make sure the default agent image is on the daemon. Never raises."""
    try:
        ref = await asyncio.to_thread(
            provision.pull_or_verify_image,
            docker_client,
            settings,
            settings.agent_image_tag,
        )
        log.debug("agent image present: %s", ref)
    except provision.ImageUnavailable as e:
        log.warning("agent image pre-pull failed (will retry next tick): %s", e)
    except Exception:  # noqa: BLE001 — a sweep must never die
        log.exception("agent image pre-pull failed unexpectedly")


async def prepull_loop(docker_client: Any, settings: Settings) -> None:
    """Run ensure_agent_image immediately, then every image_prepull_interval_seconds.

    Runs immediately (unlike app._bg_loop, which sleeps first) so a version bump
    followed by a control-plane restart warms the new tag before the first create.
    """
    while True:
        await ensure_agent_image(docker_client, settings)
        await asyncio.sleep(settings.image_prepull_interval_seconds)

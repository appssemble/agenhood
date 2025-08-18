from __future__ import annotations

import asyncio
from typing import Any

import httpx

from control_plane.config import Settings

_REPO = "agent-runtime"


def _local_tags(docker_client: Any) -> set[str]:
    """Tags of locally-present ``agent-runtime`` images (covers dev builds)."""
    if docker_client is None:
        return set()
    tags: set[str] = set()
    for img in docker_client.images.list(name=_REPO):
        for ref in (img.tags or []):
            repo, _, tag = ref.rpartition(":")
            if tag and repo.split("/")[-1] == _REPO:
                tags.add(tag)
    return tags


async def _registry_tags(settings: Settings) -> list[str]:
    """Query the registry v2 ``tags/list`` endpoint. Raises on any failure."""
    url = f"https://{settings.agent_registry}/v2/{_REPO}/tags/list"
    auth: tuple[str, str] | None = None
    if settings.agent_registry_username:
        auth = (settings.agent_registry_username, settings.agent_registry_password)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, auth=auth)
        resp.raise_for_status()
        data = resp.json()
    return list(data.get("tags") or [])


async def list_image_tags(settings: Settings, docker_client: Any) -> dict:
    """Merge registry + local tags. Registry source wins on collision.

    Never raises: if the registry is unreachable, returns local tags only with
    ``registry_unavailable=True``.
    """
    registry_unavailable = False
    reg_tags: list[str] = []
    if settings.agent_registry:
        try:
            reg_tags = await _registry_tags(settings)
        except Exception:
            registry_unavailable = True

    local = await asyncio.to_thread(_local_tags, docker_client)

    by_tag: dict[str, str] = {}
    for t in reg_tags:
        by_tag[t] = "registry"
    for t in local:
        by_tag.setdefault(t, "local")

    tags = [{"tag": t, "source": by_tag[t]} for t in sorted(by_tag)]
    return {
        "tags": tags,
        "default_tag": settings.agent_image_tag,
        "registry_unavailable": registry_unavailable,
    }

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


def _tags_list_url(agent_registry: str) -> str:
    """Build the v2 ``tags/list`` URL for the ``agent-runtime`` repo.

    ``agent_registry`` is the image-ref prefix — everything before
    ``/agent-runtime:<tag>`` — e.g. a bare host ``registry.example.com`` or a
    host+namespace like ``ghcr.io/appssemble``. The registry HOST is only the
    first path segment; any remaining segments are the repository namespace. The
    Docker v2 API always lives directly under the host at ``/v2/``, so the
    namespace must come AFTER ``/v2/``:
    ``https://<host>/v2/<namespace>/agent-runtime/tags/list``. (Putting the whole
    prefix before ``/v2/`` — the old behavior — 404s on GHCR.)
    """
    host, _, namespace = agent_registry.partition("/")
    repo = f"{namespace}/{_REPO}" if namespace else _REPO
    return f"https://{host}/v2/{repo}/tags/list"


def _parse_bearer_challenge(header: str) -> dict[str, str]:
    """Parse a ``Www-Authenticate: Bearer realm="...",service="...",...`` header
    into its comma-separated key="value" params. Returns {} if not a Bearer
    challenge."""
    scheme, _, rest = header.partition(" ")
    if scheme.lower() != "bearer":
        return {}
    params: dict[str, str] = {}
    for part in rest.split(","):
        key, _, val = part.strip().partition("=")
        if key:
            params[key.strip()] = val.strip().strip('"')
    return params


async def _registry_tags(settings: Settings) -> list[str]:
    """Query the registry v2 ``tags/list`` endpoint. Raises on any failure.

    Supports both direct/basic-auth registries and token-auth registries (GHCR,
    Docker Hub): the latter answer the first request with ``401`` + a Bearer
    ``Www-Authenticate`` challenge pointing at a token endpoint — even for PUBLIC
    repos, where the token is issued anonymously. We honor the challenge once and
    retry with the issued bearer token.
    """
    url = _tags_list_url(settings.agent_registry)
    basic: tuple[str, str] | None = None
    if settings.agent_registry_username:
        basic = (settings.agent_registry_username, settings.agent_registry_password)

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, auth=basic)

        if resp.status_code == 401:
            chal = _parse_bearer_challenge(resp.headers.get("www-authenticate", ""))
            realm = chal.get("realm")
            if realm:
                token_params = {k: chal[k] for k in ("service", "scope") if k in chal}
                # Send basic creds to the token endpoint only if we have them;
                # public GHCR issues an anonymous token without any.
                tok = await client.get(realm, params=token_params, auth=basic)
                tok.raise_for_status()
                body = tok.json()
                token = body.get("token") or body.get("access_token")
                if token:
                    resp = await client.get(
                        url, headers={"Authorization": f"Bearer {token}"}
                    )

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

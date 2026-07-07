from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from control_plane import registry
from control_plane.auth import Principal
from control_plane.auth.principal import resolve_principal

router = APIRouter(tags=["Images"])


class ImageTag(BaseModel):
    tag: str = Field(description="Container image tag (e.g. `latest` or a version).")
    source: str = Field(
        description="Where the tag was discovered (e.g. the registry or local Docker)."
    )


class ImageTagsResponse(BaseModel):
    tags: list[ImageTag] = Field(description="Available image tags for provisioning containers.")
    default_tag: str = Field(
        description="Tag used when a container is created without an explicit tag."
    )
    registry_unavailable: bool = Field(
        description=(
            "True when the remote registry could not be reached, so tags reflect only "
            "local Docker."
        )
    )


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _docker(request: Request) -> Any:
    return getattr(request.app.state, "docker_client", None)


@router.get(
    "/images/tags",
    response_model=ImageTagsResponse,
    response_description=(
        "Available container image tags plus the default tag and registry reachability."
    ),
)
async def list_image_tags(
    request: Request,
    _principal: Principal = Depends(resolve_principal),
) -> ImageTagsResponse:
    """List container image tags available for provisioning.

    Combines tags from the configured remote registry with those present in
    local Docker, reporting the default tag used when none is specified and
    whether the registry was reachable (`registry_unavailable`).

    Any authenticated principal may call this endpoint (no side effects).
    """
    result = await registry.list_image_tags(_settings(request), _docker(request))
    return ImageTagsResponse(**result)

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from control_plane import registry
from control_plane.auth import Principal
from control_plane.auth.principal import resolve_principal

router = APIRouter()


class ImageTag(BaseModel):
    tag: str
    source: str


class ImageTagsResponse(BaseModel):
    tags: list[ImageTag]
    default_tag: str
    registry_unavailable: bool


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _docker(request: Request) -> Any:
    return getattr(request.app.state, "docker_client", None)


@router.get("/images/tags", response_model=ImageTagsResponse)
async def list_image_tags(
    request: Request,
    _principal: Principal = Depends(resolve_principal),
) -> ImageTagsResponse:
    result = await registry.list_image_tags(_settings(request), _docker(request))
    return ImageTagsResponse(**result)

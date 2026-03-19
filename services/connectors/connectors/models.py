from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NormalizedEvent(BaseModel):
    provider: str
    event_type: str
    external_delivery_id: str
    resource: str | None = None          # repo full name / channel
    thread_key: str | None = None        # stable per-conversation key
    text: str = ""                       # comment/message body
    origin_ref: dict[str, Any] = Field(default_factory=dict)
    actor: str | None = None
    external_id: str | None = None       # workspace/installation id for tenant isolation


class RenderUpdate(BaseModel):
    """A coalesced render to push to the provider message."""
    body: str
    final: bool = False

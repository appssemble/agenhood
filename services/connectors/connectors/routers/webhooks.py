from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse

from connectors.orchestrator import handle_event

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/{provider_name}")
async def receive(
    provider_name: str, request: Request, background_tasks: BackgroundTasks
) -> Response:
    provider = request.app.state.providers.get(provider_name)
    if provider is None:
        return Response(status_code=404)
    raw = await request.body()

    # Slack URL verification handshake.
    if provider_name == "slack":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if parsed.get("type") == "url_verification":
            return Response(content=parsed.get("challenge", ""),
                            media_type="text/plain")

    if not provider.verify_webhook(dict(request.headers), raw):
        return Response(status_code=401)

    payload = json.loads(raw)
    if provider_name == "github":
        payload["_github_event"] = request.headers.get("X-GitHub-Event")
        payload["_delivery_id"] = request.headers.get("X-GitHub-Delivery")

    result = await handle_event(
        provider=provider, payload=payload,
        factory=request.app.state.session_factory,
        cp_client=request.app.state.cp_client,
        master_key=request.app.state.master_key,
        coalesce_ms=request.app.state.settings.relay_coalesce_ms,
        background_tasks=background_tasks,
    )
    return JSONResponse(result)

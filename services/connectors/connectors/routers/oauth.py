from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from connectors.connections_service import build_connection_row
from connectors.tables import connections

router = APIRouter(prefix="/v1/oauth", tags=["oauth"])


def _parse_state(state: str) -> tuple[str, str]:
    tenant_id, _, cp_api_key = state.partition("|")
    return tenant_id, cp_api_key


async def _persist_connection(request: Request, row: dict) -> JSONResponse:  # type: ignore[type-arg]
    insert = {k: v for k, v in row.items() if not k.startswith("_")}
    async with request.app.state.session_factory() as s:
        await s.execute(sa.insert(connections).values(**insert))
        await s.commit()
    return JSONResponse({"status": "connected", "connection_id": row["id"]})


@router.get("/slack/callback")
async def slack_callback(code: str, state: str, request: Request) -> JSONResponse:
    tenant_id, cp_api_key = _parse_state(state)
    provider = request.app.state.providers["slack"]
    data = await provider.exchange_oauth_code(code)
    row = build_connection_row(
        tenant_id=tenant_id, provider="slack",
        external_id=data["team"]["id"], display_name=data["team"].get("name", "Slack"),
        access_token=data["access_token"], refresh_token=None, token_expires_at=None,
        cp_api_key=cp_api_key, scopes=data.get("scope", ""),
        metadata={"bot_user_id": data.get("bot_user_id")},
        master_key=request.app.state.master_key,
    )
    return await _persist_connection(request, row)


@router.get("/github/callback")
async def github_callback(
    installation_id: str, state: str, request: Request
) -> JSONResponse:
    tenant_id, cp_api_key = _parse_state(state)
    row = build_connection_row(
        tenant_id=tenant_id, provider="github",
        external_id=installation_id, display_name=f"GitHub install {installation_id}",
        access_token=None, refresh_token=None, token_expires_at=None,
        cp_api_key=cp_api_key, scopes="", metadata={},
        master_key=request.app.state.master_key,
    )
    return await _persist_connection(request, row)

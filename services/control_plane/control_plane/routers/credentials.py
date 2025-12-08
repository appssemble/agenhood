from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.anthropic_oauth import build_authorize_url, exchange_code, gen_pkce
from control_plane.audit import audit
from control_plane.auth.crypto import decrypt_secret, load_key_from_env
from control_plane.auth.principal import (
    Principal,
    actor_type_for,
    require_session_admin,
)
from control_plane.config import Settings
from control_plane.credentials_service import build_credential_row
from control_plane.errors import api_error
from control_plane.oauth_service import (
    _finish_connection,
    _store_oauth_credential,
    create_connection,
    get_connection,
)
from control_plane.openai_oauth import DeviceFlowError, start_device_flow
from control_plane.sse import format_sse

router = APIRouter(prefix="/v1/credentials", tags=["credentials"])

_KNOWN_PROVIDERS = {"anthropic", "openai"}


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class SetCredential(BaseModel):
    provider: str
    api_key: str


class StartOAuth(BaseModel):
    tos_acknowledged: bool = False


class CompleteOAuth(BaseModel):
    connection_id: str
    code: str


@router.get("")
async def list_credentials(
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    rows = (
        await conn.execute(
            sa.select(
                t.credentials.c.id,
                t.credentials.c.provider,
                t.credentials.c.key_last4,
                t.credentials.c.auth_method,
                t.credentials.c.status,
                t.credentials.c.oauth_metadata,
                t.credentials.c.token_expires_at,
                t.credentials.c.created_by,
                t.credentials.c.created_at,
            ).where(t.credentials.c.tenant_id == p.tenant_id)
        )
    ).mappings().all()

    def _account_tail(meta: dict | None) -> str | None:  # type: ignore[type-arg]
        acct = (meta or {}).get("account_id")
        return acct[-4:] if isinstance(acct, str) and acct else None

    # Never return ciphertext/tokens — only provider + last4/account tail + status.
    return {
        "credentials": [
            {
                "id": r["id"],
                "provider": r["provider"],
                "auth_method": r["auth_method"],
                "status": r["status"],
                "last4": r["key_last4"],
                "account_tail": _account_tail(r["oauth_metadata"]),
                "expires_at": (
                    r["token_expires_at"].isoformat() if r["token_expires_at"] else None
                ),
                "created_by": r["created_by"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("", status_code=201)
async def set_credential(
    body: SetCredential,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if body.provider not in _KNOWN_PROVIDERS:
        raise api_error(400, "validation_error", "Unknown provider", "provider")
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "A credential belongs to a tenant")
    master = load_key_from_env()
    row = build_credential_row(
        tenant_id=p.tenant_id,
        provider=body.provider,
        api_key=body.api_key,
        created_by=p.user_id,
        master_key=master,
    )
    # One credential per (tenant, provider, auth_method): replace any existing api_key.
    await conn.execute(
        sa.delete(t.credentials).where(
            t.credentials.c.tenant_id == p.tenant_id,
            t.credentials.c.provider == body.provider,
            t.credentials.c.auth_method == "api_key",
        )
    )
    await conn.execute(sa.insert(t.credentials).values(**row))
    actor_type = actor_type_for(p)
    await audit(
        conn,
        actor_type=actor_type,
        actor_id=p.user_id,
        action="credential.store",
        target_type="credential",
        target_id=body.provider,
        # details MUST NOT contain the secret — last4 only.
        details={"last4": row["key_last4"]},
    )
    await conn.commit()
    # Never return the secret — provider + last4 only.
    return {
        "id": row["id"],
        "provider": row["provider"],
        "last4": row["key_last4"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


@router.delete("/{cid}")
async def delete_credential(
    cid: str,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = (
        await conn.execute(sa.select(t.credentials).where(t.credentials.c.id == cid))
    ).mappings().first()
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "Credential not found")
    provider = row["provider"]
    await conn.execute(sa.delete(t.credentials).where(t.credentials.c.id == cid))
    actor_type = actor_type_for(p)
    await audit(
        conn,
        actor_type=actor_type,
        actor_id=p.user_id,
        action="credential.remove",
        target_type="credential",
        target_id=provider,
        details={"credential_id": cid},
    )
    await conn.commit()
    return {"id": cid, "deleted": True}


_PROVIDER_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI"}


@router.get("/providers")
async def list_api_key_providers(
    request: Request,
    p: Principal = Depends(require_session_admin),
) -> dict:  # type: ignore[type-arg]
    """Providers a tenant can store an API key for, derived from the model catalog.

    Returns every provider that has an ``api_key``-category model. Drives the
    Credentials UI's provider dropdown so it tracks the catalog automatically
    instead of a hardcoded list (an unknown provider falls back to a title-cased
    id). Providers offered only via subscription/OAuth are excluded — there is no
    API key to paste for them.
    """
    catalog = request.app.state.model_catalog
    providers = sorted({e.provider for e in catalog if e.category == "api_key"})
    return {
        "providers": [
            {"id": pr, "label": _PROVIDER_LABELS.get(pr, pr.title())} for pr in providers
        ]
    }


@router.post("/oauth/openai/start", status_code=201)
async def start_openai_oauth(
    body: StartOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if not body.tos_acknowledged:
        raise api_error(
            400, "tos_required",
            "You must confirm you are connecting your own ChatGPT account",
        )
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "A credential belongs to a tenant")
    settings: Settings = request.app.state.settings
    if settings.oauth_subscription_kill_switch:
        raise api_error(400, "oauth_disabled", "Subscription auth is disabled")
    df = await start_device_flow(settings)
    master = load_key_from_env()
    # The poller needs both the device_auth_id and the user_code to poll; stash
    # them together (encrypted) as the connection's opaque device-code secret.
    device_secret = json.dumps(
        {"device_auth_id": df["device_auth_id"], "user_code": df["user_code"]}
    )
    cid = await create_connection(
        conn,
        tenant_id=p.tenant_id,
        provider="openai",
        device_code=device_secret,
        expires_in=int(df.get("expires_in", 900)),
        master_key=master,
    )
    await audit(
        conn,
        actor_type=actor_type_for(p),
        actor_id=p.user_id,
        action="credential.oauth_start",
        target_type="credential",
        target_id="openai",
        details={"connection_id": cid, "tos_acknowledged": body.tos_acknowledged},
    )
    await conn.commit()
    return {
        "connection_id": cid,
        "user_code": df.get("user_code"),
        "verification_uri": df.get("verification_uri"),
        "verification_uri_complete": df.get("verification_uri_complete"),
        "expires_in": int(df.get("expires_in", 900)),
        "interval": int(df.get("interval", 5)),
    }


@router.get("/oauth/openai/connections/{connection_id}")
async def get_oauth_connection(
    connection_id: str,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    row = await get_connection(conn, connection_id)
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "Connection not found")
    return {
        "connection_id": row["id"],
        "status": row["status"],
        "error": row["error"],
        "credential_id": row["credential_id"],
    }


@router.get("/oauth/openai/connections/{connection_id}/events")
async def stream_oauth_connection(
    connection_id: str,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> StreamingResponse:
    row = await get_connection(conn, connection_id)
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "Connection not found")
    bus = request.app.state.oauth_events

    async def gen():  # type: ignore[no-untyped-def]
        import asyncio as _asyncio

        def _frame(status: str) -> str:
            return format_sse(json.dumps({"status": status}))

        # Already terminal → emit once and close.
        if row["status"] != "pending":
            yield _frame(row["status"])
            return

        deadline = row["expires_at"]
        q = bus.register(connection_id)
        try:
            while True:
                if await request.is_disconnected():
                    return
                if datetime.now(UTC) >= deadline:
                    yield _frame("timeout")
                    return
                try:
                    status = await _asyncio.wait_for(q.get(), timeout=2.0)
                    yield _frame(status)
                    if status != "pending":
                        return
                except TimeoutError:
                    # Cross-replica fallback: poll the DB.
                    factory = request.app.state.session_factory
                    async with factory() as s2:
                        cur = await get_connection(s2, connection_id)
                    if cur and cur["status"] != "pending":
                        yield _frame(cur["status"])
                        return
        finally:
            bus.unregister(connection_id)

    return StreamingResponse(
        gen(),  # type: ignore[no-untyped-call]
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/oauth/anthropic/start", status_code=201)
async def start_anthropic_oauth(
    body: StartOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    if not body.tos_acknowledged:
        raise api_error(
            400, "tos_required",
            "You must confirm you are connecting your own Claude account",
        )
    if p.tenant_id is None:
        raise api_error(400, "validation_error", "A credential belongs to a tenant")
    settings: Settings = request.app.state.settings
    if settings.oauth_subscription_kill_switch:
        raise api_error(400, "oauth_disabled", "Subscription auth is disabled")
    verifier, challenge = gen_pkce()
    state = secrets.token_urlsafe(24)
    master = load_key_from_env()
    # Stash the PKCE verifier + state (encrypted) in the connection's secret blob.
    cid = await create_connection(
        conn,
        tenant_id=p.tenant_id,
        provider="anthropic",
        device_code=json.dumps({"code_verifier": verifier, "state": state}),
        expires_in=600,
        master_key=master,
    )
    authorize_url = build_authorize_url(settings, state=state, code_challenge=challenge)
    await audit(
        conn,
        actor_type=actor_type_for(p),
        actor_id=p.user_id,
        action="credential.oauth_start",
        target_type="credential",
        target_id="anthropic",
        details={"connection_id": cid, "tos_acknowledged": body.tos_acknowledged},
    )
    await conn.commit()
    return {"connection_id": cid, "authorize_url": authorize_url}


@router.post("/oauth/anthropic/complete")
async def complete_anthropic_oauth(
    body: CompleteOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    settings: Settings = request.app.state.settings
    if settings.oauth_subscription_kill_switch:
        raise api_error(400, "oauth_disabled", "Subscription auth is disabled")
    master = load_key_from_env()
    row = await get_connection(conn, body.connection_id)
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "Connection not found")
    if row["provider"] != "anthropic":
        raise api_error(400, "wrong_provider", "Not an Anthropic connection")
    if row["status"] != "pending":
        raise api_error(400, "invalid_state", f"Connection already {row['status']}")
    blob = json.loads(decrypt_secret(row["device_code_ciphertext"], master))
    # The pasted code may arrive as "<code>#<state>"; split and validate state.
    auth_code, _, pasted_state = body.code.strip().partition("#")
    # If the paste carried no "#state", skip the check — PKCE (code_verifier)
    # already binds the exchange to this connection; state is a secondary guard.
    if pasted_state and pasted_state != blob["state"]:
        raise api_error(400, "state_mismatch", "Authorization state mismatch")
    bus = request.app.state.oauth_events
    try:
        tokens = await exchange_code(
            settings, code=auth_code, code_verifier=blob["code_verifier"], state=blob["state"]
        )
    except DeviceFlowError as exc:
        await _finish_connection(conn, bus, row["id"], "failed", error=exc.code)
        await conn.commit()
        return {"connection_id": row["id"], "status": "failed",
                "credential_id": None, "error": exc.code}
    cred_id = await _store_oauth_credential(
        conn, tenant_id=row["tenant_id"], provider="anthropic",
        tokens=tokens, master_key=master, now=datetime.now(UTC),
    )
    await _finish_connection(conn, bus, row["id"], "connected", credential_id=cred_id)
    await audit(
        conn,
        actor_type=actor_type_for(p),
        actor_id=p.user_id,
        action="credential.oauth_complete",
        target_type="credential",
        target_id="anthropic",
        details={"connection_id": row["id"], "credential_id": cred_id},
    )
    await conn.commit()
    return {"connection_id": row["id"], "status": "connected",
            "credential_id": cred_id, "error": None}


@router.get("/_internal/decrypt/{cid}")
async def _internal_decrypt(
    cid: str,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Internal endpoint for task runners to retrieve decrypted credentials.
    Scoped to staff only and never exposed in the public API docs.

    For oauth_subscription credentials this returns the ACCESS token only —
    never the refresh token (spec §8)."""
    if not p.is_staff:
        raise api_error(403, "forbidden", "Staff only")
    row = (
        await conn.execute(sa.select(t.credentials).where(t.credentials.c.id == cid))
    ).mappings().first()
    if not row:
        raise api_error(404, "not_found", "Credential not found")
    master = load_key_from_env()
    if row["auth_method"] == "oauth_subscription":
        from control_plane.credentials_service import decrypt_oauth_row

        data = decrypt_oauth_row(dict(row), master)
        return {
            "id": cid,
            "provider": row["provider"],
            "auth_method": "oauth_subscription",
            "access_token": data["access_token"],
            "account_id": data["account_id"],
        }
    from control_plane.credentials_service import decrypt_row

    secret = decrypt_row(dict(row), master)
    return {"id": cid, "provider": row["provider"], "auth_method": "api_key", "api_key": secret}

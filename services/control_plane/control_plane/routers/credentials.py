from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
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
from control_plane.credentials_service import build_credential_row, credential_provider_for
from control_plane.errors import api_error
from control_plane.oauth_service import (
    _finish_connection,
    _store_oauth_credential,
    create_connection,
    get_connection,
)
from control_plane.openai_oauth import DeviceFlowError, start_device_flow
from control_plane.sse import format_sse

router = APIRouter(prefix="/v1/credentials", tags=["Credentials"])

_KNOWN_PROVIDERS = {"anthropic", "openai", "opencode"}


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


class SetCredential(BaseModel):
    provider: Annotated[
        str,
        Field(
            description=(
                "LLM provider id; must be a known provider "
                "(`anthropic`, `openai`, or `opencode`)."
            )
        ),
    ]
    api_key: Annotated[
        str,
        Field(
            description=(
                "The provider API key to store. Encrypted at rest; only its last 4 "
                "chars are ever returned."
            )
        ),
    ]


class StartOAuth(BaseModel):
    tos_acknowledged: Annotated[
        bool,
        Field(
            description=(
                "Must be `true` to confirm you are connecting your own provider "
                "subscription account; the request is rejected otherwise."
            )
        ),
    ] = False


class CompleteOAuth(BaseModel):
    connection_id: Annotated[
        str, Field(description="Id of the pending OAuth connection to finalize.")
    ]
    code: Annotated[
        str,
        Field(
            description=(
                "Authorization code pasted by the user. May arrive as "
                "`<code>#<state>`; the optional `#state` suffix is validated when present."
            )
        ),
    ]


class CredentialView(BaseModel):
    """Non-secret view of a stored credential (never includes keys/tokens)."""

    id: Annotated[str, Field(description="Credential id.")]
    provider: Annotated[
        str, Field(description="Provider the credential is for (e.g. `anthropic`, `openai`).")
    ]
    auth_method: Annotated[
        str,
        Field(description="How the credential authenticates: `api_key` or `oauth_subscription`."),
    ]
    status: Annotated[str, Field(description="Credential status (e.g. active).")]
    last4: Annotated[
        str | None,
        Field(
            description=(
                "Last 4 characters of the API key, for identification; null for OAuth "
                "credentials."
            )
        ),
    ]
    account_tail: Annotated[
        str | None,
        Field(description="Last 4 characters of the linked OAuth account id, if any."),
    ]
    expires_at: Annotated[
        str | None,
        Field(description="ISO-8601 token expiry for OAuth credentials, or null."),
    ]
    created_by: Annotated[
        str | None, Field(description="User id that created the credential, if known.")
    ]
    created_at: Annotated[datetime, Field(description="When the credential was created (UTC).")]


class CredentialList(BaseModel):
    """Wrapper for the list-credentials response."""

    credentials: Annotated[
        list[CredentialView],
        Field(description="The tenant's stored credentials (no secrets)."),
    ]


class SetCredentialResult(BaseModel):
    """Result of storing an API-key credential (no secret returned)."""

    id: Annotated[str, Field(description="Id of the stored credential.")]
    provider: Annotated[str, Field(description="Provider the credential is for.")]
    last4: Annotated[str, Field(description="Last 4 characters of the stored API key.")]
    created_by: Annotated[
        str | None, Field(description="User id that stored the credential, if known.")
    ]
    created_at: Annotated[datetime, Field(description="When the credential was stored (UTC).")]


class DeleteCredentialResult(BaseModel):
    """Result of deleting a credential."""

    id: Annotated[str, Field(description="Id of the deleted credential.")]
    deleted: Annotated[bool, Field(description="Always `true` on success.")]


class ProviderInfo(BaseModel):
    """A provider a tenant can store an API key for."""

    id: Annotated[str, Field(description="Provider id (e.g. `openai`).")]
    label: Annotated[str, Field(description="Human-readable provider label for display.")]


class ProviderList(BaseModel):
    """Wrapper for the list-providers response."""

    providers: Annotated[
        list[ProviderInfo],
        Field(description="Providers with an API-key model in the catalog."),
    ]


class OpenAiOAuthStart(BaseModel):
    """Device-flow details returned when starting the OpenAI OAuth connection."""

    connection_id: Annotated[str, Field(description="Id of the newly created pending connection.")]
    user_code: Annotated[
        str | None, Field(description="Code the user enters at the verification URI.")
    ]
    verification_uri: Annotated[
        str | None, Field(description="URI where the user authorizes the device.")
    ]
    verification_uri_complete: Annotated[
        str | None,
        Field(description="Verification URI with the user code pre-filled."),
    ]
    expires_in: Annotated[int, Field(description="Seconds until the device code expires.")]
    interval: Annotated[int, Field(description="Recommended polling interval in seconds.")]


class ConnectionStatus(BaseModel):
    """Current status of an OAuth connection."""

    connection_id: Annotated[str, Field(description="Id of the connection.")]
    status: Annotated[
        str,
        Field(description="Connection status: `pending`, `connected`, `failed`, or `timeout`."),
    ]
    error: Annotated[
        str | None, Field(description="Error code if the connection failed, else null.")
    ]
    credential_id: Annotated[
        str | None,
        Field(description="Id of the credential created on success, else null."),
    ]


class AnthropicOAuthStart(BaseModel):
    """Result of starting the Anthropic OAuth (PKCE) flow."""

    connection_id: Annotated[str, Field(description="Id of the newly created pending connection.")]
    authorize_url: Annotated[
        str, Field(description="URL the user opens to authorize and obtain the code.")
    ]


class OAuthCompleteResult(BaseModel):
    """Result of completing the Anthropic OAuth flow (success or failure)."""

    connection_id: Annotated[str, Field(description="Id of the connection.")]
    status: Annotated[
        str, Field(description="Final status: `connected` on success, `failed` on error.")
    ]
    credential_id: Annotated[
        str | None,
        Field(description="Id of the stored OAuth credential on success, else null."),
    ]
    error: Annotated[str | None, Field(description="Error code on failure, else null.")]


@router.get(
    "",
    response_model=CredentialList,
    response_description="The tenant's stored credentials (no secrets).",
)
async def list_credentials(
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """List the tenant's stored provider credentials (no secrets).

    Requires a tenant-scoped admin/owner **user session**. Ciphertext, API keys,
    and OAuth tokens are never returned — only provider, auth method, status, and
    non-secret tails (key last4 / account tail) plus timestamps.

    Errors: 403 `forbidden` if the caller is not a tenant admin/owner or
    authenticates with an API key instead of a session.
    """
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


@router.post(
    "",
    status_code=201,
    response_model=SetCredentialResult,
    response_description="The stored credential's id, provider, and key last4 (no secret).",
)
async def set_credential(
    body: SetCredential,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Store (or replace) a provider API-key credential for the tenant.

    Requires a tenant-scoped admin/owner **user session**. The key is encrypted
    at rest with the master key. Only one api_key credential per
    (tenant, provider) is kept — any existing one is replaced. Writes a
    `credential.store` audit entry (last4 only, never the secret). The response
    never contains the secret — only its last 4 characters.

    Errors: 400 `validation_error` if `provider` is not a known provider or the
    session has no active tenant; 403 `forbidden` if the caller is not a tenant
    admin/owner or uses an API key instead of a session.
    """
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


@router.delete(
    "/{cid}",
    response_model=DeleteCredentialResult,
    response_description="The deleted credential's id and a success flag.",
)
async def delete_credential(
    cid: Annotated[str, Path(description="Id of the credential to delete.")],
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Delete a stored credential (destructive, irreversible).

    Requires a tenant-scoped admin/owner **user session**; staff may delete any
    tenant's credential. Removes the row and writes a `credential.remove` audit
    entry.

    Errors: 404 `not_found` if the credential does not exist or belongs to
    another tenant (non-staff callers); 403 `forbidden` if the caller is not a
    tenant admin/owner or uses an API key instead of a session.
    """
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


_PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "opencode": "OpenCode (Zen / Go)",
}


@router.get(
    "/providers",
    response_model=ProviderList,
    response_description="Providers that accept a pasteable API key.",
)
async def list_api_key_providers(
    request: Request,
    p: Principal = Depends(require_session_admin),
) -> dict:  # type: ignore[type-arg]
    """List providers a tenant can store an API key for.

    Requires a tenant-scoped admin/owner **user session**. Derived from the
    model catalog: returns every provider that has an ``api_key``-category model.
    Drives the Credentials UI's provider dropdown so it tracks the catalog
    automatically instead of a hardcoded list (an unknown provider falls back to
    a title-cased id). Providers offered only via subscription/OAuth are excluded
    — there is no API key to paste for them. Aliased catalog providers (e.g. ``opencode-go``) are folded into the provider id the key is stored under.

    Errors: 403 `forbidden` if the caller is not a tenant admin/owner or uses an
    API key instead of a session.
    """
    catalog = request.app.state.model_catalog
    # Fold aliased catalog providers (opencode-go) into the provider id the
    # credential is actually stored under, so the dropdown offers it once.
    providers = sorted({
        credential_provider_for(e.provider) for e in catalog if e.category == "api_key"
    })
    return {
        "providers": [
            {"id": pr, "label": _PROVIDER_LABELS.get(pr, pr.title())} for pr in providers
        ]
    }


@router.post(
    "/oauth/openai/start",
    status_code=201,
    response_model=OpenAiOAuthStart,
    response_description="Device-flow codes and URIs the user needs to authorize.",
)
async def start_openai_oauth(
    body: StartOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Start the OpenAI (ChatGPT subscription) OAuth device flow.

    Requires a tenant-scoped admin/owner **user session**. Kicks off a device
    flow, creates a `pending` connection storing the device-auth id and user code
    (encrypted), and writes a `credential.oauth_start` audit entry. The caller
    displays the returned `user_code`/`verification_uri` and then watches the
    connection's SSE events stream for completion.

    Errors: 400 `tos_required` if `tos_acknowledged` is not true; 400
    `validation_error` if the session has no active tenant; 400 `oauth_disabled`
    if the subscription-auth kill switch is on; 403 `forbidden` if the caller is
    not a tenant admin/owner or uses an API key instead of a session.
    """
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


@router.get(
    "/oauth/openai/connections/{connection_id}",
    response_model=ConnectionStatus,
    response_description="The connection's current status, error, and credential id.",
)
async def get_oauth_connection(
    connection_id: Annotated[str, Path(description="Id of the OAuth connection to poll.")],
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Get the current status of an OAuth connection (one-shot poll).

    Requires a tenant-scoped admin/owner **user session**; staff may read any
    tenant's connection. Use this to poll for completion when not consuming the
    SSE events stream.

    Errors: 404 `not_found` if the connection does not exist or belongs to
    another tenant (non-staff callers); 403 `forbidden` if the caller is not a
    tenant admin/owner or uses an API key instead of a session.
    """
    row = await get_connection(conn, connection_id)
    if not row or (not p.is_staff and row["tenant_id"] != p.tenant_id):
        raise api_error(404, "not_found", "Connection not found")
    return {
        "connection_id": row["id"],
        "status": row["status"],
        "error": row["error"],
        "credential_id": row["credential_id"],
    }


@router.get(
    "/oauth/openai/connections/{connection_id}/events",
    response_description=(
        "A `text/event-stream` (SSE) of JSON `{\"status\": ...}` frames. Emits the "
        "current status and closes once terminal (`connected`/`failed`/`timeout`); "
        "streams `pending` until then or until the client disconnects."
    ),
)
async def stream_oauth_connection(
    connection_id: Annotated[
        str, Path(description="Id of the OAuth connection to stream events for.")
    ],
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> StreamingResponse:
    """Stream OAuth connection status updates as Server-Sent Events.

    Requires a tenant-scoped admin/owner **user session**; staff may stream any
    tenant's connection. Returns a `text/event-stream` (SSE) response: each frame
    is a JSON `{"status": ...}`. If the connection is already terminal it emits
    once and closes; otherwise it pushes updates from the in-process event bus
    (with a DB poll fallback across replicas), a `timeout` frame at the deadline,
    and closes on the first terminal status or on client disconnect.

    Errors: 404 `not_found` if the connection does not exist or belongs to
    another tenant (non-staff callers); 403 `forbidden` if the caller is not a
    tenant admin/owner or uses an API key instead of a session.
    """
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


@router.post(
    "/oauth/anthropic/start",
    status_code=201,
    response_model=AnthropicOAuthStart,
    response_description="The pending connection id and the authorize URL to open.",
)
async def start_anthropic_oauth(
    body: StartOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Start the Anthropic (Claude subscription) OAuth PKCE flow.

    Requires a tenant-scoped admin/owner **user session**. Generates a PKCE
    verifier/challenge and state, creates a `pending` connection storing the
    verifier and state (encrypted), builds the authorize URL, and writes a
    `credential.oauth_start` audit entry. The user opens `authorize_url`, then
    the pasted code is submitted to `/oauth/anthropic/complete`.

    Errors: 400 `tos_required` if `tos_acknowledged` is not true; 400
    `validation_error` if the session has no active tenant; 400 `oauth_disabled`
    if the subscription-auth kill switch is on; 403 `forbidden` if the caller is
    not a tenant admin/owner or uses an API key instead of a session.
    """
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


@router.post(
    "/oauth/anthropic/complete",
    response_model=OAuthCompleteResult,
    response_description="The connection's final status, credential id, and any error.",
)
async def complete_anthropic_oauth(
    body: CompleteOAuth,
    request: Request,
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Complete the Anthropic OAuth flow by exchanging the pasted code.

    Requires a tenant-scoped admin/owner **user session**; staff may complete any
    tenant's connection. Validates the optional `#state` suffix, exchanges the
    code (bound by the stored PKCE verifier), and on success stores the OAuth
    credential and marks the connection `connected` (writes a
    `credential.oauth_complete` audit entry). If the token exchange fails, the
    connection is marked `failed` and a 200 response with `status="failed"` and
    the error code is returned (not an HTTP error).

    Errors: 404 `not_found` if the connection does not exist or belongs to
    another tenant; 400 `wrong_provider` if it is not an Anthropic connection;
    400 `invalid_state` if the connection is not `pending`; 400 `state_mismatch`
    if a pasted state does not match; 400 `oauth_disabled` if the kill switch is
    on; 403 `forbidden` if the caller is not a tenant admin/owner or uses an API
    key instead of a session.
    """
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


@router.get(
    "/_internal/decrypt/{cid}",
    response_description=(
        "Decrypted secret material. For api_key credentials: `{id, provider, "
        "auth_method, api_key}`. For oauth_subscription: `{id, provider, "
        "auth_method, access_token, account_id}` (access token only)."
    ),
)
async def _internal_decrypt(
    cid: Annotated[str, Path(description="Id of the credential to decrypt.")],
    p: Principal = Depends(require_session_admin),
    conn: AsyncSession = Depends(_session),
) -> dict:  # type: ignore[type-arg]
    """Retrieve a decrypted credential for internal task runners.

    INTERNAL-ONLY: this endpoint is intended solely for the platform's task
    runners and is scoped to staff. It returns plaintext secret material and is
    not part of the public API surface.

    Requires a **staff** principal (returns 403 otherwise, even for tenant
    admins). For `oauth_subscription` credentials it returns the ACCESS token
    only — never the refresh token (spec §8); for `api_key` credentials it
    returns the decrypted API key. The returned keys differ by auth method.

    Errors: 403 `forbidden` if the caller is not staff; 404 `not_found` if the
    credential does not exist.
    """
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

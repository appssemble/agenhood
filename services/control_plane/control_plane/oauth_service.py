"""DB orchestration for ChatGPT subscription OAuth: device-flow connections,
the background poller, and token refresh (spec §5.2, §6.1).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import control_plane.tables as t
from control_plane.anthropic_oauth import refresh_access_token as _anthropic_refresh
from control_plane.audit import audit
from control_plane.auth.crypto import decrypt_secret, encrypt_secret
from control_plane.config import Settings
from control_plane.credentials_service import (
    build_oauth_credential_row,
    decrypt_oauth_row,
    oauth_metadata_blob,
)
from control_plane.ids_compat import new_id
from control_plane.openai_oauth import (
    DeviceFlowError,
    DeviceFlowPending,
    exchange_device_code,
    refresh_access_token,
)

log = logging.getLogger("oauth")

_PERMANENT_REFRESH_ERRORS = frozenset(
    {"invalid_grant", "invalid_request", "access_denied", "unauthorized_client", "invalid_client"}
)


async def create_connection(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    device_code: str,
    expires_in: int,
    master_key: bytes,
) -> str:
    now = datetime.now(UTC)
    cid = new_id("oac")
    await session.execute(
        sa.insert(t.oauth_connections).values(
            id=cid,
            tenant_id=tenant_id,
            provider=provider,
            device_code_ciphertext=encrypt_secret(device_code, master_key),
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in),
        )
    )
    return cid


async def get_connection(
    session: AsyncSession, connection_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            sa.select(t.oauth_connections).where(
                t.oauth_connections.c.id == connection_id
            )
        )
    ).mappings().first()
    return dict(row) if row else None


async def oauth_poll_sweep(
    db: AsyncSession,
    _docker_client: Any,
    _shim: Any,
    *,
    settings: Settings,
    master_key: bytes,
    event_bus: Any,
) -> None:
    """Poll every pending device-flow connection once.

    Signature matches app._bg_loop's fn(db, docker_client, shim, **kwargs) call.
    """
    now = datetime.now(UTC)
    pending = (
        await db.execute(
            sa.select(t.oauth_connections).where(t.oauth_connections.c.status == "pending")
        )
    ).mappings().all()
    for row in pending:
        try:
            if row["expires_at"] <= now:
                await _finish_connection(db, event_bus, row["id"], "timeout", error="expired")
                continue
            blob = json.loads(decrypt_secret(row["device_code_ciphertext"], master_key))
            try:
                tokens = await exchange_device_code(
                    settings, blob["device_auth_id"], blob["user_code"]
                )
            except DeviceFlowPending:
                continue  # keep polling next sweep
            except DeviceFlowError as exc:
                await _finish_connection(db, event_bus, row["id"], "failed", error=exc.code)
                continue
            cred_id = await _store_oauth_credential(
                db,
                tenant_id=row["tenant_id"],
                provider=row["provider"],
                tokens=tokens,
                master_key=master_key,
                now=now,
            )
            await _finish_connection(db, event_bus, row["id"], "connected", credential_id=cred_id)
        except Exception:  # noqa: BLE001 — one bad connection must not starve the rest
            log.exception("oauth_poll_sweep: skipping connection %s", row["id"])
            continue
    await db.commit()


async def oauth_connection_sweep(db: AsyncSession, _docker_client: Any, _shim: Any) -> None:
    """Delete expired oauth_connections rows (hourly)."""
    await db.execute(
        sa.delete(t.oauth_connections).where(
            t.oauth_connections.c.expires_at < datetime.now(UTC)
        )
    )
    await db.commit()


async def _finish_connection(
    db: AsyncSession,
    event_bus: Any,
    connection_id: str,
    status: str,
    *,
    error: str | None = None,
    credential_id: str | None = None,
) -> None:
    await db.execute(
        sa.update(t.oauth_connections)
        .where(t.oauth_connections.c.id == connection_id)
        .values(status=status, error=error, credential_id=credential_id)
    )
    if event_bus is not None:
        event_bus.publish(connection_id, status)


async def _store_oauth_credential(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    tokens: dict[str, Any],
    master_key: bytes,
    now: datetime,
) -> str:
    row = build_oauth_credential_row(
        tenant_id=tenant_id,
        provider=provider,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_expires_at=now + timedelta(seconds=int(tokens["expires_in"])),
        account_id=tokens.get("account_id"),
        id_token=tokens.get("id_token"),
        created_by=None,
        master_key=master_key,
    )
    # Upsert scoped by (tenant, provider, auth_method) so it coexists with an api_key.
    await db.execute(
        sa.delete(t.credentials).where(
            t.credentials.c.tenant_id == tenant_id,
            t.credentials.c.provider == provider,
            t.credentials.c.auth_method == "oauth_subscription",
        )
    )
    await db.execute(sa.insert(t.credentials).values(**row))
    return str(row["id"])


class OAuthReauthRequired(Exception):
    """The subscription refresh token is no longer valid; the tenant must reconnect."""


async def ensure_fresh_oauth(
    session: AsyncSession,
    cred_row: dict,  # type: ignore[type-arg]
    *,
    settings: Settings,
    master_key: bytes,
    now: datetime,
) -> dict[str, Any]:
    """Return a non-stale access token, refreshing + persisting under a row lock.

    Returns {access_token, refresh_token, account_id, expires_at}. Raises
    OAuthReauthRequired on a permanent refresh failure (and marks the credential
    status=reauth_required). The refresh_token is returned because opencode's
    Codex loader requires it in auth.json to register the credential (Approach B).
    """
    data = decrypt_oauth_row(cred_row, master_key)
    expires_at: datetime = cred_row["token_expires_at"]
    grace = timedelta(seconds=settings.oauth_subscription_grace_seconds)
    if expires_at is not None and expires_at > now + grace:
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "account_id": data["account_id"],
            "id_token": data.get("id_token"),
            "expires_at": expires_at,
        }

    # Lock the row so concurrent submits don't stampede the token endpoint.
    locked = (
        await session.execute(
            sa.select(t.credentials)
            .where(t.credentials.c.id == cred_row["id"])
            .with_for_update()
        )
    ).mappings().first()
    assert locked is not None, "credential row disappeared between read and lock"
    locked_data = decrypt_oauth_row(dict(locked), master_key)
    locked_expires: datetime = locked["token_expires_at"]
    if locked_expires is not None and locked_expires > now + grace:
        # Another worker already refreshed while we waited for the lock.
        return {
            "access_token": locked_data["access_token"],
            "refresh_token": locked_data["refresh_token"],
            "account_id": locked_data["account_id"],
            "id_token": locked_data.get("id_token"),
            "expires_at": locked_expires,
        }

    try:
        tokens = await _refresh_with_retry(
            settings, locked_data["refresh_token"], provider=cred_row["provider"]
        )
    except DeviceFlowError as exc:
        if exc.code in _PERMANENT_REFRESH_ERRORS:
            await session.execute(
                sa.update(t.credentials)
                .where(t.credentials.c.id == cred_row["id"])
                .values(status="reauth_required")
            )
        raise OAuthReauthRequired() from None

    new_expires = now + timedelta(seconds=int(tokens["expires_in"]))
    # A refresh may return a fresh id_token; if it doesn't, keep the stored one.
    new_id_token = tokens.get("id_token") or locked_data.get("id_token")
    await session.execute(
        sa.update(t.credentials)
        .where(t.credentials.c.id == cred_row["id"])
        .values(
            access_token_ciphertext=encrypt_secret(tokens["access_token"], master_key),
            refresh_token_ciphertext=encrypt_secret(tokens["refresh_token"], master_key),
            token_expires_at=new_expires,
            oauth_metadata=oauth_metadata_blob(
                account_id=locked_data["account_id"],
                id_token=new_id_token,
                master_key=master_key,
            ),
            status="active",
            updated_at=now,
        )
    )
    await audit(
        session,
        actor_type="system",
        actor_id=None,
        action="credential.refresh",
        target_type="credential",
        target_id=cred_row["id"],
        details={},
    )
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "account_id": locked_data["account_id"],
        "id_token": new_id_token,
        "expires_at": new_expires,
    }


async def _refresh_with_retry(
    settings: Settings, refresh_token: str, provider: str = "openai"
) -> dict[str, Any]:
    """Refresh with a small retry budget on transient (non-DeviceFlowError) errors."""
    import asyncio as _asyncio

    refresh_fn = _anthropic_refresh if provider == "anthropic" else refresh_access_token
    last: Exception | None = None
    for attempt in range(3):
        try:
            return await refresh_fn(settings, refresh_token)
        except DeviceFlowError:
            raise  # permanent — do not retry
        except Exception as exc:  # noqa: BLE001 — transient network/5xx
            last = exc
            await _asyncio.sleep(0.1 * (2 ** attempt))
    raise DeviceFlowError("refresh_transient_exhausted") from last

"""OpenAI device-flow OAuth client (ChatGPT subscription) — HTTP + JWT only.

No database access here. Endpoints/client_id come from Settings so an operator
can patch this unofficial surface without a code change (spec §5.3, §9).
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from control_plane._oauth_http import TIMEOUT, log, safe_json
from control_plane.config import Settings


class DeviceFlowPending(Exception):
    """The user has not yet authorized; keep polling."""

    def __init__(self, slow_down: bool = False) -> None:
        super().__init__("authorization_pending")
        self.slow_down = slow_down


class DeviceFlowError(Exception):
    """A terminal device-flow / refresh failure (denied, expired, invalid_grant)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def start_device_flow(settings: Settings) -> dict[str, Any]:
    """Begin the device flow against OpenAI's (unofficial Codex) deviceauth endpoint.

    The endpoint takes a JSON body and returns
    ``{device_auth_id, user_code, interval (str), expires_at (ISO)}`` — NOT the
    standard OAuth device-flow shape, and NO verification URL (the user enters the
    code at a fixed page, ``settings.openai_oauth_verification_uri``).

    Returns a normalized dict:
    ``{device_auth_id, user_code, interval, expires_in, verification_uri}``.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.openai_oauth_device_code_url,
            json={
                "client_id": settings.openai_oauth_client_id,
                "scope": settings.openai_oauth_scopes,
            },
        )
    resp.raise_for_status()
    body = safe_json(resp)
    expires_in = 900
    exp = body.get("expires_at")
    if isinstance(exp, str):
        try:
            delta = datetime.fromisoformat(exp) - datetime.now(UTC)
            expires_in = max(60, int(delta.total_seconds()))
        except ValueError:
            pass
    try:
        interval = int(body.get("interval", 5))
    except (TypeError, ValueError):
        interval = 5
    return {
        "device_auth_id": body.get("device_auth_id", ""),
        "user_code": body.get("user_code", ""),
        "interval": interval,
        "expires_in": expires_in,
        "verification_uri": settings.openai_oauth_verification_uri,
    }


async def exchange_device_code(
    settings: Settings, device_auth_id: str, user_code: str
) -> dict[str, Any]:
    """Poll the deviceauth token endpoint for a connected subscription.

    The endpoint takes a JSON body ``{device_auth_id, user_code, client_id}``.
    While the user has not authorized it returns HTTP 403 with
    ``error.code == "deviceauth_authorization_pending"`` -> DeviceFlowPending.
    Any other 4xx is a terminal DeviceFlowError. On success returns
    ``{access_token, refresh_token, account_id, expires_in}``.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.openai_oauth_token_url,
            json={
                "device_auth_id": device_auth_id,
                "user_code": user_code,
                "client_id": settings.openai_oauth_client_id,
            },
        )
    body = safe_json(resp)
    if resp.status_code >= 400:
        code = _error_code(body)
        if "authorization_pending" in code:
            raise DeviceFlowPending()
        if "slow_down" in code:
            raise DeviceFlowPending(slow_down=True)
        raise DeviceFlowError(code or f"http_{resp.status_code}")
    # 200 = the user authorized. The deviceauth endpoint returns a PKCE
    # authorization_code (+ server-generated code_verifier), NOT the tokens — we
    # must redeem the code at oauth/token. Log KEYS only (never values).
    log.info("deviceauth authorized: keys=%s", sorted(body.keys()))
    auth_code = body.get("authorization_code")
    code_verifier = body.get("code_verifier")
    if not isinstance(auth_code, str) or not auth_code:
        # Authorized-but-no-code intermediate state → keep polling.
        raise DeviceFlowPending()
    return await _redeem_authorization_code(
        settings, auth_code, code_verifier if isinstance(code_verifier, str) else ""
    )


async def _redeem_authorization_code(
    settings: Settings, code: str, code_verifier: str
) -> dict[str, Any]:
    """Exchange a device-flow authorization_code for the real tokens at oauth/token.

    Returns {access_token, refresh_token, account_id, expires_in}.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.openai_oauth_refresh_url,  # the oauth/token endpoint
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": settings.openai_oauth_client_id,
                "redirect_uri": settings.openai_oauth_redirect_uri,
            },
        )
    body = safe_json(resp)
    if resp.status_code >= 400:
        # The error envelope is non-secret; log it so the exact format issue
        # (content-type / redirect_uri / missing field) is pinpointed in one try.
        log.warning(
            "oauth/token authorization_code exchange failed: status=%s body=%s",
            resp.status_code,
            body,
        )
        raise DeviceFlowError(_error_code(body) or f"http_{resp.status_code}")
    log.info("oauth/token exchange success: keys=%s", sorted(body.keys()))
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise DeviceFlowError("malformed_token_response")
    refresh = body.get("refresh_token")
    id_token = body.get("id_token", "")
    return {
        "access_token": access,
        "refresh_token": refresh if isinstance(refresh, str) else "",
        "account_id": extract_account_id(id_token) or extract_account_id(access),
        # codex's auth.json requires the id_token; opencode ignores it.
        "id_token": id_token if isinstance(id_token, str) else "",
        "expires_in": int(body.get("expires_in", 3600)),
    }


def _error_code(body: dict[str, Any]) -> str:
    """Extract a comparable error code from an OpenAI error envelope."""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("type") or "")
    if isinstance(err, str):
        return err
    return ""


async def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    """Refresh an access token. Returns {access_token, refresh_token, expires_in}.

    Raises DeviceFlowError on a permanent failure (e.g. invalid_grant).
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.openai_oauth_refresh_url,
            data={
                "client_id": settings.openai_oauth_client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
    body = safe_json(resp)
    if resp.status_code >= 400:
        err = str(body.get("error", "")) if isinstance(body, dict) else ""
        raise DeviceFlowError(err or f"http_{resp.status_code}")
    if "access_token" not in body:
        raise DeviceFlowError("malformed_token_response")
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token", refresh_token),
        # A refresh may return a fresh id_token; "" if the endpoint omits it
        # (the caller then keeps the previously stored one).
        "id_token": body.get("id_token", "") if isinstance(body, dict) else "",
        "expires_in": int(body.get("expires_in", 3600)),
    }


def extract_account_id(id_token: str) -> str | None:
    """Read the ChatGPT account id from a JWT id_token (no signature check).

    Claim precedence: root ``chatgpt_account_id`` ->
    ``https://api.openai.com/auth.chatgpt_account_id`` -> ``organizations[0].id``.
    """
    claims = _decode_jwt_payload(id_token)
    if not claims:
        return None
    root = claims.get("chatgpt_account_id")
    if isinstance(root, str):
        return root
    auth = claims.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        nested = auth.get("chatgpt_account_id")
        if isinstance(nested, str):
            return nested
    orgs = claims.get("organizations")
    if isinstance(orgs, list) and orgs and isinstance(orgs[0], dict):
        oid = orgs[0].get("id")
        if isinstance(oid, str):
            return oid
    return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    seg = parts[1]
    seg += "=" * (-len(seg) % 4)  # restore base64 padding
    try:
        raw = base64.urlsafe_b64decode(seg)
        data = json.loads(raw)
    except (binascii.Error, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

"""Anthropic claude.ai OAuth client (Claude Code subscription) — HTTP + PKCE only.

No DB access. Endpoints/client_id/scopes come from Settings so an operator can
patch this UNDOCUMENTED, reverse-engineered surface without a code change. The
Anthropic OAuth endpoints are not officially documented and are migrating
(console.anthropic.com -> platform.claude.com); treat every URL as version-
sensitive. Permanent failures raise ``DeviceFlowError`` (reused from
``openai_oauth``) so ``ensure_fresh_oauth``'s handling is identical.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from control_plane._oauth_http import TIMEOUT, log, safe_json
from control_plane.config import Settings
from control_plane.openai_oauth import DeviceFlowError


def gen_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256 (url-safe, unpadded)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(settings: Settings, *, state: str, code_challenge: str) -> str:
    """Build the claude.ai authorize URL (Authorization Code + PKCE)."""
    params = {
        "response_type": "code",
        "client_id": settings.anthropic_oauth_client_id,
        "redirect_uri": settings.anthropic_oauth_redirect_uri,
        "scope": settings.anthropic_oauth_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.anthropic_oauth_authorize_url}?{urlencode(params)}"


async def exchange_code(
    settings: Settings, *, code: str, code_verifier: str, state: str
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    Returns ``{access_token, refresh_token, account_id, id_token, expires_in}``.
    Raises ``DeviceFlowError`` on any non-2xx.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.anthropic_oauth_token_url,
            json={
                "grant_type": "authorization_code",
                "code": code,
                "state": state,
                "client_id": settings.anthropic_oauth_client_id,
                "redirect_uri": settings.anthropic_oauth_redirect_uri,
                "code_verifier": code_verifier,
            },
        )
    return _tokens(resp, "exchange")


async def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    """Refresh tokens. Returns ``{access_token, refresh_token, id_token, expires_in}``.

    The returned ``refresh_token`` ROTATES (single-use) — callers MUST persist it.
    Raises ``DeviceFlowError`` on a permanent (4xx) failure.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            settings.anthropic_oauth_token_url,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.anthropic_oauth_client_id,
            },
        )
    return _tokens(resp, "refresh", fallback_refresh=refresh_token)


def _tokens(resp: httpx.Response, op: str, *, fallback_refresh: str = "") -> dict[str, Any]:
    body = safe_json(resp)
    if resp.status_code >= 400:
        err = str(body.get("error", ""))
        log.warning("anthropic oauth %s failed: status=%s err=%s", op, resp.status_code, err)
        raise DeviceFlowError(err or f"http_{resp.status_code}")
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise DeviceFlowError("malformed_token_response")
    refresh = body.get("refresh_token")
    return {
        "access_token": access,
        "refresh_token": refresh if isinstance(refresh, str) and refresh else fallback_refresh,
        # Anthropic has no id_token; ensure_fresh_oauth keeps the stored account_id.
        "id_token": "",
        "account_id": _account_id(body),
        "expires_in": int(body.get("expires_in", 28800)),
    }


def _account_id(body: dict[str, Any]) -> str | None:
    for key in ("account", "organization"):
        obj = body.get(key)
        if isinstance(obj, dict):
            v = obj.get("uuid") or obj.get("id")
            if isinstance(v, str) and v:
                return v
    return None

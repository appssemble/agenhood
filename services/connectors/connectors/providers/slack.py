from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from connectors.models import NormalizedEvent

_SLACK_API = "https://slack.com/api"
_HTTP_TIMEOUT_SECONDS = 20
_MAX_SKEW = 300  # 5 minutes


class SlackProvider:
    name = "slack"

    def __init__(self, *, signing_secret: str, client_id: str, client_secret: str):
        self.signing_secret = signing_secret
        self.client_id = client_id
        self.client_secret = client_secret

    def _client(self) -> httpx.AsyncClient:
        transport = getattr(self, "_transport", None)
        return httpx.AsyncClient(
            base_url=_SLACK_API,
            transport=transport,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )

    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> bool:
        ts = headers.get("X-Slack-Request-Timestamp") or headers.get(
            "x-slack-request-timestamp"
        )
        sig = headers.get("X-Slack-Signature") or headers.get("x-slack-signature")
        if not ts or not sig:
            return False
        try:
            if abs(time.time() - int(ts)) > _MAX_SKEW:
                return False
        except ValueError:
            return False
        base = f"v0:{ts}:{raw_body.decode()}".encode()
        expected = "v0=" + hmac.new(
            self.signing_secret.encode(), base, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    def normalize_event(self, payload: dict[str, Any]) -> NormalizedEvent | None:
        if payload.get("type") != "event_callback":
            return None
        ev = payload.get("event", {})
        if ev.get("type") not in ("app_mention", "message"):
            return None
        if ev.get("bot_id"):  # ignore the bot's own messages
            return None
        channel = ev.get("channel")
        thread_ts = ev.get("thread_ts") or ev.get("ts")
        return NormalizedEvent(
            provider="slack",
            event_type=ev["type"],
            external_delivery_id=payload.get("event_id", ""),
            resource=channel,
            thread_key=f"{channel}:{thread_ts}",
            text=ev.get("text", ""),
            origin_ref={"channel": channel, "thread_ts": thread_ts},
            actor=ev.get("user"),
            external_id=payload.get("team_id"),
        )

    async def mint_token(self, connection_row: dict[str, Any], master_key: bytes) -> str:
        from connectors.connections_service import decrypt_access_token

        return decrypt_access_token(connection_row, master_key)

    async def post_initial(
        self, token: str, origin_ref: dict[str, Any], body: str
    ) -> dict[str, Any]:
        async with self._client() as c:
            resp = await c.post(
                "/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": origin_ref["channel"],
                    "thread_ts": origin_ref["thread_ts"],
                    "text": body,
                },
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"slack post failed: {data.get('error')}")
            return {"channel": data["channel"], "ts": data["ts"]}

    async def update_message(
        self, token: str, handle: dict[str, Any], body: str
    ) -> None:
        async with self._client() as c:
            resp = await c.post(
                "/chat.update",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": handle["channel"], "ts": handle["ts"], "text": body},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"slack update failed: {data.get('error')}")

    async def exchange_oauth_code(self, code: str) -> dict[str, Any]:
        async with self._client() as c:
            resp = await c.post("/oauth.v2.access", data={
                "code": code, "client_id": self.client_id,
                "client_secret": self.client_secret,
            })
            data: dict[str, Any] = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"slack oauth failed: {data.get('error')}")
            return data

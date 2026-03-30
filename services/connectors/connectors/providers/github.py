from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, cast

import httpx
import jwt

from connectors.models import NormalizedEvent

_GH_API = "https://api.github.com"
_HTTP_TIMEOUT_SECONDS = 20
_JWT_ISSUED_AT_SKEW_SECONDS = 60
_JWT_TTL_SECONDS = 540
_TOKEN_REFRESH_SKEW_SECONDS = 60
_TOKEN_CACHE_TTL_SECONDS = 3000

# The webhook router injects these two synthetic keys before normalize:
#   _github_event  = X-GitHub-Event header
#   _delivery_id   = X-GitHub-Delivery header


class GitHubProvider:
    name = "github"

    def __init__(self, *, app_id: str, private_key_pem: str, webhook_secret: str):
        self.app_id = app_id
        self.private_key_pem = private_key_pem
        self.webhook_secret = webhook_secret

    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> bool:
        sig = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
        if not sig:
            return False
        expected = "sha256=" + hmac.new(
            self.webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    def normalize_event(self, payload: dict[str, Any]) -> NormalizedEvent | None:
        event = payload.get("_github_event")
        delivery = payload.get("_delivery_id", "")
        if event == "issue_comment" and payload.get("action") == "created":
            repo = payload["repository"]["full_name"]
            number = payload["issue"]["number"]
            comment = payload["comment"]
            raw_inst_id = payload.get("installation", {}).get("id")
            return NormalizedEvent(
                provider="github",
                event_type="issue_comment",
                external_delivery_id=delivery,
                resource=repo,
                thread_key=f"{repo}#{number}",
                text=comment.get("body", ""),
                origin_ref={"repo": repo, "number": number, "comment_id": comment["id"]},
                actor=payload.get("sender", {}).get("login"),
                external_id=str(raw_inst_id) if raw_inst_id is not None else None,
            )
        # Other event types (pull_request_review_comment, issues opened) added as needed.
        return None

    def _client(self) -> httpx.AsyncClient:
        transport = getattr(self, "_transport", None)
        return httpx.AsyncClient(
            base_url=_GH_API,
            transport=transport,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )

    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - _JWT_ISSUED_AT_SKEW_SECONDS,
            "exp": now + _JWT_TTL_SECONDS,
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key_pem, algorithm="RS256")

    async def mint_token(self, connection_row: dict[str, Any], master_key: bytes) -> str:
        # GitHub installation tokens last ~1h; cache per installation in-memory.
        cache = getattr(self, "_tok_cache", None)
        if cache is None:
            cache = {}
            self._tok_cache = cache
        installation_id = connection_row["external_id"]
        cached = cache.get(installation_id)
        if cached and cached[1] > time.time() + _TOKEN_REFRESH_SKEW_SECONDS:
            return cast(str, cached[0])
        async with self._client() as c:
            resp = await c.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {self._app_jwt()}",
                         "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            token = cast(str, resp.json()["token"])
        cache[installation_id] = (token, time.time() + _TOKEN_CACHE_TTL_SECONDS)
        return token

    async def post_initial(
        self, token: str, origin_ref: dict[str, Any], body: str
    ) -> dict[str, Any]:
        repo, number = origin_ref["repo"], origin_ref["number"]
        async with self._client() as c:
            resp = await c.post(
                f"/repos/{repo}/issues/{number}/comments",
                headers={"Authorization": f"Bearer {token}"},
                json={"body": body},
            )
            resp.raise_for_status()
            return {"repo": repo, "comment_id": resp.json()["id"]}

    async def update_message(
        self, token: str, handle: dict[str, Any], body: str
    ) -> None:
        async with self._client() as c:
            resp = await c.patch(
                f"/repos/{handle['repo']}/issues/comments/{handle['comment_id']}",
                headers={"Authorization": f"Bearer {token}"},
                json={"body": body},
            )
            resp.raise_for_status()

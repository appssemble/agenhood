from __future__ import annotations

import hmac

from fastapi import HTTPException


class TokenAuth:
    """Constant-time bearer-token check against the configured SHIM_TOKEN.

    An empty configured token disables auth (local dev / hand-run containers).
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def check(self, authorization: str | None) -> None:
        if not self._token:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        presented = authorization[len("Bearer "):]
        if not hmac.compare_digest(presented, self._token):
            raise HTTPException(status_code=401, detail="invalid token")

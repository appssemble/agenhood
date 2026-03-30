from __future__ import annotations

from typing import Any, Protocol

from connectors.models import NormalizedEvent


class Provider(Protocol):
    name: str

    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> bool: ...

    def normalize_event(self, payload: dict[str, Any]) -> NormalizedEvent | None: ...

    async def mint_token(self, connection_row: dict[str, Any], master_key: bytes) -> str: ...

    async def post_initial(
        self, token: str, origin_ref: dict[str, Any], body: str
    ) -> dict[str, Any]:
        """Returns a provider_message_handle (dict) for later edits."""
        ...

    async def update_message(
        self, token: str, handle: dict[str, Any], body: str
    ) -> None: ...

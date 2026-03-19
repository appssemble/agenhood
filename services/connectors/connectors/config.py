from __future__ import annotations

import os
from dataclasses import dataclass


def _asyncpg_url(url: str) -> str:
    """Coerce any Postgres URL to SQLAlchemy's async (asyncpg) dialect.

    Managed providers (Coolify, Heroku, ...) hand out ``postgres://`` URLs, but
    SQLAlchemy dropped the bare ``postgres`` alias and needs an explicit driver,
    so accept ``postgres://`` / ``postgresql://`` and normalize to asyncpg.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    master_key_b64: str | None
    control_plane_base_url: str
    relay_coalesce_ms: int
    slack_signing_secret: str | None
    slack_client_id: str | None
    slack_client_secret: str | None
    github_app_id: str | None
    github_app_private_key: str | None  # PEM
    github_webhook_secret: str | None
    public_base_url: str  # connectors' own public URL, for OAuth redirect URIs

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            database_url=_asyncpg_url(
                os.environ.get(
                    "CONNECTORS_DATABASE_URL",
                    "postgresql+asyncpg://postgres:postgres@localhost:5432/connectors",
                )
            ),
            master_key_b64=os.environ.get("CONNECTORS_MASTER_KEY") or None,
            control_plane_base_url=os.environ.get(
                "CONTROL_PLANE_BASE_URL", "http://control-plane:8000"
            ),
            relay_coalesce_ms=int(os.environ.get("RELAY_COALESCE_MS", "1000")),
            slack_signing_secret=os.environ.get("SLACK_SIGNING_SECRET") or None,
            slack_client_id=os.environ.get("SLACK_CLIENT_ID") or None,
            slack_client_secret=os.environ.get("SLACK_CLIENT_SECRET") or None,
            github_app_id=os.environ.get("GITHUB_APP_ID") or None,
            github_app_private_key=os.environ.get("GITHUB_APP_PRIVATE_KEY") or None,
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET") or None,
            public_base_url=os.environ.get(
                "CONNECTORS_PUBLIC_BASE_URL", "http://localhost:8090"
            ),
        )

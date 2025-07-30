from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_kv(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


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
    seed_tenant_id: str
    seed_api_key: str
    seed_llm_api_key: str
    agent_image_tag: str
    internal_network: str
    readyz_timeout_seconds: float
    shim_port: int
    # Registry prefix for the runtime-provisioned agent image. Empty => bare local
    # tag "agent-runtime:<tag>" (single-host, no pull). Set to e.g.
    # "registry.example.com" to provision from a self-hosted registry (Coolify).
    agent_registry: str = ""
    # Credentials the control plane uses to pull the (private) agent image. The
    # runtime pull is initiated by docker-py INSIDE this container, so a host
    # `docker login` is not seen — these env creds are passed as auth_config.
    agent_registry_username: str = ""
    agent_registry_password: str = ""
    # Per-agent container resource caps (env-tunable for VM sizing). Defaults match
    # the historical hardcoded values so behavior is unchanged when unset.
    agent_mem_limit: str = "4g"
    agent_memswap_limit: str = "4g"
    agent_cpus: float = 2.0
    agent_pids_limit: int = 512
    agent_extra_env: dict[str, str] = field(default_factory=dict)
    # When True, provision_container binds the shim port to an ephemeral host
    # port so the control plane process (running outside Docker) can reach it.
    # Useful on macOS where container IPs are not routable from the host.
    bind_shim_port_to_host: bool = False
    # Bootstrap break-glass staff key (env ADMIN_API_KEY). Optional.
    admin_api_key: str | None = None
    # Seeded staff (admin) login, created idempotently by the seed when both
    # email + password are set. The intended first-login path (vs. bootstrapping
    # via ADMIN_API_KEY). The seeded user must change the password on first login.
    seed_staff_email: str = ""
    seed_staff_password: str = ""
    seed_staff_name: str = "Admin"
    # Base-64-encoded 32-byte AES key (env CREDENTIAL_ENCRYPTION_KEY). Optional.
    credential_encryption_key: str | None = None
    # Whether the session cookie carries the Secure flag. Must be True in prod
    # (TLS via Traefik); set False for plain-HTTP local dev or browsers drop it.
    session_cookie_secure: bool = True
    # Maximum number of workspaces a regular (non-staff) user may own. Staff are exempt.
    max_owned_tenants_per_user: int = 20
    # --- ChatGPT subscription (OpenAI device-flow OAuth) ---
    oauth_subscription_kill_switch: bool = False
    oauth_subscription_grace_seconds: int = 300
    oauth_poll_sweep_interval_seconds: int = 5
    oauth_poll_max_interval_seconds: int = 120
    oauth_connection_sweep_interval_seconds: int = 3600
    openai_oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    openai_oauth_scopes: str = "openid profile email offline_access"
    openai_oauth_device_code_url: str = (
        "https://auth.openai.com/api/accounts/deviceauth/usercode"
    )
    openai_oauth_token_url: str = (
        "https://auth.openai.com/api/accounts/deviceauth/token"
    )
    openai_oauth_refresh_url: str = "https://auth.openai.com/oauth/token"
    # The page where the user enters the device user_code (no URL is returned by
    # the usercode endpoint). Configurable so it can be swapped without a deploy.
    openai_oauth_verification_uri: str = "https://auth.openai.com/codex/device"
    # Redirect URI used when redeeming the device-flow authorization_code at
    # oauth/token (PKCE). The DEVICE flow uses the deviceauth callback (the
    # browser flow would use http://localhost:1455/auth/callback instead).
    openai_oauth_redirect_uri: str = "https://auth.openai.com/deviceauth/callback"
    # --- Claude Code subscription (Anthropic claude.ai OAuth, PKCE) ---
    # UNDOCUMENTED/reverse-engineered; every value overridable. Endpoints are
    # migrating (console.anthropic.com -> platform.claude.com) — change via env.
    anthropic_oauth_client_id: str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    anthropic_oauth_authorize_url: str = "https://claude.ai/oauth/authorize"
    anthropic_oauth_token_url: str = "https://console.anthropic.com/v1/oauth/token"
    anthropic_oauth_redirect_uri: str = (
        "https://console.anthropic.com/oauth/code/callback"
    )
    anthropic_oauth_scopes: str = "user:inference user:profile"

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            database_url=_asyncpg_url(
                os.environ.get(
                    "DATABASE_URL",
                    "postgresql+asyncpg://postgres:postgres@localhost:5432/agentruntime",
                )
            ),
            seed_tenant_id=os.environ.get("SEED_TENANT_ID", "ten_seed"),
            # Default empty so running the seed on a real deploy never mints a
            # public/default API key; dev (.env.dev) and tests set this explicitly.
            seed_api_key=os.environ.get("SEED_API_KEY", ""),
            seed_llm_api_key=os.environ.get("SEED_LLM_API_KEY", ""),
            seed_staff_email=os.environ.get("SEED_STAFF_EMAIL", ""),
            seed_staff_password=os.environ.get("SEED_STAFF_PASSWORD", ""),
            seed_staff_name=os.environ.get("SEED_STAFF_NAME", "Admin"),
            agent_image_tag=os.environ.get("AGENT_IMAGE_TAG", "dev"),
            agent_registry=os.environ.get("AGENT_REGISTRY", ""),
            agent_registry_username=os.environ.get("AGENT_REGISTRY_USERNAME", ""),
            agent_registry_password=os.environ.get("AGENT_REGISTRY_PASSWORD", ""),
            agent_mem_limit=os.environ.get("AGENT_MEM_LIMIT", "4g"),
            agent_memswap_limit=os.environ.get(
                "AGENT_MEMSWAP_LIMIT", os.environ.get("AGENT_MEM_LIMIT", "4g")
            ),
            agent_cpus=float(os.environ.get("AGENT_CPUS", "2")),
            agent_pids_limit=int(os.environ.get("AGENT_PIDS_LIMIT", "512")),
            internal_network=os.environ.get("INTERNAL_NETWORK", "agent-runtime-internal"),
            readyz_timeout_seconds=float(os.environ.get("READYZ_TIMEOUT_SECONDS", "30")),
            shim_port=int(os.environ.get("SHIM_PORT", "8080")),
            agent_extra_env=_parse_kv(os.environ.get("AGENT_EXTRA_ENV", "")),
            bind_shim_port_to_host=os.environ.get("BIND_SHIM_PORT_TO_HOST", "").lower()
                in ("1", "true", "yes"),
            admin_api_key=os.environ.get("ADMIN_API_KEY") or None,
            credential_encryption_key=os.environ.get("CREDENTIAL_ENCRYPTION_KEY") or None,
            session_cookie_secure=os.environ.get("SESSION_COOKIE_SECURE", "true").lower()
                not in ("0", "false", "no"),
            oauth_subscription_kill_switch=os.environ.get(
                "OAUTH_SUBSCRIPTION_KILL_SWITCH", ""
            ).lower() in ("1", "true", "yes"),
            oauth_subscription_grace_seconds=int(
                os.environ.get("OAUTH_SUBSCRIPTION_GRACE_SECONDS", "300")
            ),
            oauth_poll_sweep_interval_seconds=int(
                os.environ.get("OAUTH_POLL_SWEEP_INTERVAL_SECONDS", "5")
            ),
            oauth_poll_max_interval_seconds=int(
                os.environ.get("OAUTH_POLL_MAX_INTERVAL_SECONDS", "120")
            ),
            oauth_connection_sweep_interval_seconds=int(
                os.environ.get("OAUTH_CONNECTION_SWEEP_INTERVAL_SECONDS", "3600")
            ),
            openai_oauth_client_id=os.environ.get(
                "OPENAI_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann"
            ),
            openai_oauth_scopes=os.environ.get(
                "OPENAI_OAUTH_SCOPES", "openid profile email offline_access"
            ),
            openai_oauth_device_code_url=os.environ.get(
                "OPENAI_OAUTH_DEVICE_CODE_URL",
                "https://auth.openai.com/api/accounts/deviceauth/usercode",
            ),
            openai_oauth_token_url=os.environ.get(
                "OPENAI_OAUTH_TOKEN_URL",
                "https://auth.openai.com/api/accounts/deviceauth/token",
            ),
            openai_oauth_refresh_url=os.environ.get(
                "OPENAI_OAUTH_REFRESH_URL", "https://auth.openai.com/oauth/token"
            ),
            openai_oauth_verification_uri=os.environ.get(
                "OPENAI_OAUTH_VERIFICATION_URI", "https://auth.openai.com/codex/device"
            ),
            openai_oauth_redirect_uri=os.environ.get(
                "OPENAI_OAUTH_REDIRECT_URI", "https://auth.openai.com/deviceauth/callback"
            ),
            anthropic_oauth_client_id=os.environ.get(
                "ANTHROPIC_OAUTH_CLIENT_ID", "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
            ),
            anthropic_oauth_authorize_url=os.environ.get(
                "ANTHROPIC_OAUTH_AUTHORIZE_URL", "https://claude.ai/oauth/authorize"
            ),
            anthropic_oauth_token_url=os.environ.get(
                "ANTHROPIC_OAUTH_TOKEN_URL",
                "https://console.anthropic.com/v1/oauth/token",
            ),
            anthropic_oauth_redirect_uri=os.environ.get(
                "ANTHROPIC_OAUTH_REDIRECT_URI",
                "https://console.anthropic.com/oauth/code/callback",
            ),
            anthropic_oauth_scopes=os.environ.get(
                "ANTHROPIC_OAUTH_SCOPES", "user:inference user:profile"
            ),
        )

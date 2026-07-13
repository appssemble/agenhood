from __future__ import annotations

import base64
from datetime import UTC, datetime

from control_plane.auth.crypto import decrypt_secret, encrypt_secret
from control_plane.ids_compat import new_id

# spec §3.5.1 / §4.4: v1 is Anthropic-only for the vanilla driver; OpenAI is the
# next adapter. Map the configured model to its credential provider.
_MODEL_PREFIX_PROVIDER = (
    ("claude", "anthropic"),
    ("gpt-", "openai"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
)

# Model-catalog providers whose credential is stored under a different provider
# id. The single "opencode" API key (from the Zen console) unlocks both paid
# opencode Zen models and the opencode-go plan's models.
_CREDENTIAL_PROVIDER_ALIASES = {"opencode-go": "opencode"}


def credential_provider_for(provider: str) -> str:
    """The provider id credential rows are stored under for ``provider``."""
    return _CREDENTIAL_PROVIDER_ALIASES.get(provider, provider)


def model_is_keyless(model: str) -> bool:
    """True if this model may run with no stored credential.

    Only opencode's built-in free Zen models (``opencode/*-free``) are keyless.
    Paid Zen models and opencode-go models require the tenant's opencode API
    key. This is the same rule model_catalog's classification uses, so the
    submit path and the catalog cannot drift.
    """
    return model.startswith("opencode/") and model.endswith("-free")


# claude-code's model catalog offers only these three bare family aliases (see
# model_catalog._CLAUDE_CODE_ALIASES) — none start with "claude", so they need
# an explicit exact-match entry alongside the prefix table above.
_CLAUDE_CODE_ALIAS_PROVIDER = {"opus": "anthropic", "sonnet": "anthropic", "haiku": "anthropic"}


def provider_for_model(model: str) -> str:
    """Resolve the credential provider for a model id.

    A fully-qualified ``provider/model`` id (e.g. ``opencode/deepseek-v4-flash-free``
    or ``anthropic/claude-...``) takes its provider from the prefix; a bare id
    (``claude-...``, ``gpt-...``) is matched against the known prefixes, and
    claude-code's bare family aliases (``opus``/``sonnet``/``haiku``) against
    the exact-match table above.
    """
    if "/" in model:
        return model.split("/", 1)[0].lower()
    m = model.lower()
    if m in _CLAUDE_CODE_ALIAS_PROVIDER:
        return _CLAUDE_CODE_ALIAS_PROVIDER[m]
    for prefix, provider in _MODEL_PREFIX_PROVIDER:
        if m.startswith(prefix):
            return provider
    raise ValueError(f"No known provider for model {model!r}")


def last4(api_key: str) -> str:
    return api_key[-4:]


def build_credential_row(
    *,
    tenant_id: str,
    provider: str,
    api_key: str,
    created_by: str | None,
    master_key: bytes,
) -> dict:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    return {
        "id": new_id("cred"),
        "tenant_id": tenant_id,
        "provider": provider,
        "auth_method": "api_key",
        "status": "active",
        "key_ciphertext": encrypt_secret(api_key, master_key),
        "key_last4": last4(api_key),
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def decrypt_row(row: dict, master_key: bytes) -> str:  # type: ignore[type-arg]
    return decrypt_secret(row["key_ciphertext"], master_key)


def oauth_metadata_blob(
    *, account_id: str | None, id_token: str | None, master_key: bytes
) -> dict:  # type: ignore[type-arg]
    """Build the oauth_metadata JSONB blob.

    ``account_id`` is stored in the clear (already derived from the public JWT).
    ``id_token`` is a credential the codex driver needs in its ``auth.json``, so
    it is encrypted (AES-GCM) and stored base64-encoded under ``id_token_ct`` —
    only present when an id_token was captured (codex needs it; opencode ignores
    it). No DB migration is required: the column already exists.
    """
    blob: dict = {"account_id": account_id}  # type: ignore[type-arg]
    if id_token:
        ct = encrypt_secret(id_token, master_key)
        blob["id_token_ct"] = base64.b64encode(ct).decode("ascii")
    return blob


def build_oauth_credential_row(
    *,
    tenant_id: str,
    provider: str,
    access_token: str,
    refresh_token: str,
    token_expires_at: datetime,
    account_id: str | None,
    created_by: str | None,
    master_key: bytes,
    id_token: str | None = None,
) -> dict:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    return {
        "id": new_id("cred"),
        "tenant_id": tenant_id,
        "provider": provider,
        "auth_method": "oauth_subscription",
        "key_ciphertext": None,
        "key_last4": None,
        "access_token_ciphertext": encrypt_secret(access_token, master_key),
        "refresh_token_ciphertext": encrypt_secret(refresh_token, master_key),
        "token_expires_at": token_expires_at,
        "oauth_metadata": oauth_metadata_blob(
            account_id=account_id, id_token=id_token, master_key=master_key
        ),
        "status": "active",
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def decrypt_oauth_row(row: dict, master_key: bytes) -> dict:  # type: ignore[type-arg]
    meta = row.get("oauth_metadata") or {}
    id_token_ct = meta.get("id_token_ct")
    id_token = (
        decrypt_secret(base64.b64decode(id_token_ct), master_key) if id_token_ct else None
    )
    return {
        "access_token": decrypt_secret(row["access_token_ciphertext"], master_key),
        "refresh_token": decrypt_secret(row["refresh_token_ciphertext"], master_key),
        "account_id": meta.get("account_id"),
        "id_token": id_token,
        "token_expires_at": row["token_expires_at"],
    }

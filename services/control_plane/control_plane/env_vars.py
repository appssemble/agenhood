"""Per-container environment variables: validation, secret encryption, and the
flat map resolved at task dispatch (spec: container env vars).

Stored JSONB item shapes (containers.env_vars / templates.env_vars):
  non-secret: {"name": N, "value": V, "secret": false}
  secret:     {"name": N, "secret": true, "ciphertext": "<b64 AES-GCM blob>"}

Pure functions of their inputs (the encryption key arrives via a loader
callable) — unit-testable without a DB, same style as resource_limits.py.
"""
from __future__ import annotations

import base64
import re
from collections.abc import Callable
from typing import Any

from control_plane.auth.crypto import decrypt_secret, encrypt_secret
from control_plane.errors import APIError, validation_error

MAX_ENV_VARS = 64
MAX_NAME_LEN = 128
MAX_VALUE_LEN = 8192

_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Names the platform owns: shim infra vars (docker_ctl/provision._env_for),
# the egress-proxy vars (a security boundary), and sandbox-controlled paths.
RESERVED_ENV_NAMES = frozenset({
    "SHIM_TOKEN", "CONTAINER_ID", "TENANT_ID", "SHIM_MAX_WORKERS",
    "SEARCH_PROVIDER_URL", "EXA_API_KEY",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "HOME", "PATH",
})


def _encryption_unavailable(exc: Exception) -> APIError:
    return APIError(
        500, "encryption_unavailable",
        "secret env vars require a configured CREDENTIAL_ENCRYPTION_KEY",
    )


def _item_field(prefix: str, idx: int, name: str) -> str:
    return f"{prefix}[{idx}].{name}"


def store_env_vars(
    incoming: list[dict[str, Any]],
    existing: list[dict[str, Any]] | None,
    key_loader: Callable[[], bytes],
    *,
    field_prefix: str = "env_vars",
) -> list[dict[str, Any]]:
    """Validate + encrypt a submitted env-var list into its stored JSONB shape.

    Full-replace semantics: the returned list is exactly what was submitted;
    items absent from ``incoming`` are dropped. A secret item with a null
    ``value`` keeps the ciphertext of the same-named secret in ``existing``
    (write-only round-trip); with no ``existing`` match that is a 400 — on
    create there is nothing to keep. The key is loaded lazily, only when a new
    secret value actually needs encrypting.
    """
    if len(incoming) > MAX_ENV_VARS:
        raise validation_error(
            f"at most {MAX_ENV_VARS} env vars are allowed", field=field_prefix
        )
    existing_secrets = {
        i["name"]: i for i in (existing or []) if i.get("secret")
    }
    seen: set[str] = set()
    stored: list[dict[str, Any]] = []
    key: bytes | None = None
    for idx, item in enumerate(incoming):
        name = item.get("name") or ""
        secret = bool(item.get("secret"))
        value = item.get("value")
        if not isinstance(name, str):
            raise validation_error(
                "name must be a string",
                field=_item_field(field_prefix, idx, "name"),
            )
        if value is not None and not isinstance(value, str):
            raise validation_error(
                "value must be a string",
                field=_item_field(field_prefix, idx, "value"),
            )
        if not _NAME_RE.fullmatch(name) or len(name) > MAX_NAME_LEN:
            raise validation_error(
                "name must be 1-128 chars matching [A-Z_][A-Z0-9_]*",
                field=_item_field(field_prefix, idx, "name"),
            )
        if name in RESERVED_ENV_NAMES:
            raise validation_error(
                f"{name} is reserved by the platform",
                field=_item_field(field_prefix, idx, "name"),
            )
        if name in seen:
            raise validation_error(
                f"duplicate env var name: {name}",
                field=_item_field(field_prefix, idx, "name"),
            )
        seen.add(name)
        if value is not None and len(value.encode("utf-8")) > MAX_VALUE_LEN:
            raise validation_error(
                f"value must be at most {MAX_VALUE_LEN} bytes",
                field=_item_field(field_prefix, idx, "value"),
            )
        if not secret:
            if value is None:
                raise validation_error(
                    "value is required for a non-secret env var",
                    field=_item_field(field_prefix, idx, "value"),
                )
            stored.append({"name": name, "value": value, "secret": False})
            continue
        if value is None:
            kept = existing_secrets.get(name)
            if kept is None:
                raise validation_error(
                    f"no stored secret named {name} to keep; provide a value",
                    field=_item_field(field_prefix, idx, "value"),
                )
            stored.append(
                {"name": name, "secret": True, "ciphertext": kept["ciphertext"]}
            )
            continue
        if key is None:
            try:
                key = key_loader()
            except ValueError as exc:
                raise _encryption_unavailable(exc) from exc
        blob = encrypt_secret(value, key)
        stored.append(
            {"name": name, "secret": True,
             "ciphertext": base64.b64encode(blob).decode("ascii")}
        )
    return stored


def public_env_vars(stored: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The masked, read-side view: secrets are write-only (value: null)."""
    out: list[dict[str, Any]] = []
    for item in stored or []:
        if item.get("secret"):
            out.append({"name": item["name"], "value": None, "secret": True})
        else:
            out.append({"name": item["name"], "value": item.get("value"), "secret": False})
    return out


def resolve_env(
    stored: list[dict[str, Any]] | None,
    key_loader: Callable[[], bytes],
) -> dict[str, str]:
    """Decrypt into the flat map shipped on ShimTaskRequest.env at dispatch.

    Decrypted values are in-memory only — same handling rules as
    llm_credential: never persisted, never logged. Failures raise (500
    encryption_unavailable) rather than silently dropping vars.
    """
    env: dict[str, str] = {}
    key: bytes | None = None
    for item in stored or []:
        if not item.get("secret"):
            env[item["name"]] = str(item.get("value") or "")
            continue
        if key is None:
            try:
                key = key_loader()
            except ValueError as exc:
                raise _encryption_unavailable(exc) from exc
        try:
            env[item["name"]] = decrypt_secret(
                base64.b64decode(item["ciphertext"]), key
            )
        except APIError:
            raise
        except Exception as exc:  # noqa: BLE001 — wrong key / corrupt blob
            raise _encryption_unavailable(exc) from exc
    return env

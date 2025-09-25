from __future__ import annotations

import hashlib
import secrets

# spec §5: api_keys.key_prefix is the "first 8 chars, for lookup + display".
API_KEY_PREFIX_LEN = 8
_API_KEY_HEAD = "tk_live_"


def generate_session_token() -> str:
    """256 bits of randomness, URL-safe, no padding (>=43 chars)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex. Used for sessions.token_hash (spec §5)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Returns (full_secret, prefix). The full secret is shown once; only the
    hash and prefix are stored. The prefix is the literal first 8 chars."""
    secret = _API_KEY_HEAD + secrets.token_urlsafe(32)
    return secret, secret[:API_KEY_PREFIX_LEN]

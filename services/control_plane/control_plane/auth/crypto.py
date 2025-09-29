from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12  # 96-bit nonce, the AES-GCM standard
_KEY_LEN = 32    # AES-256


def encrypt_secret(plaintext: str, key: bytes) -> bytes:
    """Returns nonce(12) || ciphertext+tag. AES-256-GCM."""
    if len(key) != _KEY_LEN:
        raise ValueError(f"key must be {_KEY_LEN} bytes, got {len(key)}")
    nonce = os.urandom(_NONCE_LEN)
    aead = AESGCM(key)
    ct = aead.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ct


def decrypt_secret(blob: bytes, key: bytes) -> str:
    """Inverse of encrypt_secret. Raises cryptography.exceptions.InvalidTag
    if the ciphertext or tag was tampered with, or the key is wrong."""
    if len(key) != _KEY_LEN:
        raise ValueError(f"key must be {_KEY_LEN} bytes, got {len(key)}")
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    aead = AESGCM(key)
    return aead.decrypt(nonce, ct, None).decode("utf-8")


def load_key_from_env(var: str = "CREDENTIAL_ENCRYPTION_KEY") -> bytes:
    """Decode the base64 32-byte master key from the environment."""
    raw = os.environ.get(var)
    if not raw:
        raise ValueError(f"{var} is not set")
    key = base64.b64decode(raw)
    if len(key) != _KEY_LEN:
        raise ValueError(f"{var} must decode to {_KEY_LEN} bytes, got {len(key)}")
    return key

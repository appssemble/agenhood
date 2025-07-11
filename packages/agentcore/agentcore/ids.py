from __future__ import annotations

import secrets
import time

# Crockford base32, ULID-compatible alphabet.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def ulid() -> str:
    """A 26-char ULID: 48-bit ms timestamp + 80 bits randomness."""
    ms = int(time.time() * 1000)
    rand = secrets.randbits(80)
    return _encode(ms, 10) + _encode(rand, 16)


def new_id(prefix: str) -> str:
    """Prefixed id, e.g. new_id('ten') -> 'ten_01HX...'."""
    return f"{prefix}_{ulid()}"

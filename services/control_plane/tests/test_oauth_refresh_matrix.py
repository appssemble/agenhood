"""OAuth provider-aware refresh matrix + crypto round-trip + no-secret-leak gate.

Unit D / Task 6. Targets:
- oauth_service._refresh_with_retry provider dispatch + retry budget (lines 292-304)
- credentials_service functions not exercised under -m unit by existing suites
- AES-GCM crypto round-trip (auth/crypto.py)
- No-secret-leak gate: REAL list_credentials router output is scanned for known
  secret values (access_token, refresh_token, account_id, key_ciphertext).
  A regression that adds any secret field to the REAL router projection fails here.
- ensure_fresh_oauth early-exit branch (lines ~205-215): fresh token → no refresh call.

No DB session required — provider dispatch and crypto are fully unit-testable.
DB-dependent paths (ensure_fresh_oauth full refresh, oauth_poll_sweep, etc.) belong in
integration tier and are NOT duplicated here.
"""
from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import control_plane.routers.credentials as cred_mod
from control_plane import credentials_service, oauth_service
from control_plane.auth.crypto import decrypt_secret, encrypt_secret
from control_plane.auth.principal import resolve_principal
from control_plane.credentials_service import (
    build_credential_row,
    build_oauth_credential_row,
    decrypt_oauth_row,
    decrypt_row,
    model_is_keyless,
    oauth_metadata_blob,
    provider_for_model,
)
from control_plane.openai_oauth import DeviceFlowError
from tests.api_contract.contracts import P_ADMIN, make_app

pytestmark = pytest.mark.unit

# Deterministic key for crypto round-trip assertions.
_KEY = b"A" * 32
_SECRET = "sk-ant-supersecret-REFRESH-acct-token"


# ── 1. Provider-aware refresh dispatch matrix ────────────────────────────────
#
# _refresh_with_retry selects _anthropic_refresh for provider="anthropic"
# and refresh_access_token (openai) for everything else.

@pytest.mark.parametrize("provider,expect_anthropic", [
    ("anthropic", True),
    ("openai", False),
])
async def test_refresh_picks_provider_specific_endpoint(
    provider, expect_anthropic, monkeypatch
):
    """Matrix: anthropic → _anthropic_refresh; openai → refresh_access_token."""
    called = {"anthropic": 0, "openai": 0}

    async def fake_anthropic(settings, refresh_token):
        called["anthropic"] += 1
        return {"access_token": "a", "refresh_token": "r", "id_token": "", "expires_in": 3600}

    async def fake_openai(settings, refresh_token):
        called["openai"] += 1
        return {"access_token": "a", "refresh_token": "r", "id_token": "", "expires_in": 3600}

    # Patch at the oauth_service module namespace — that is where the dispatch
    # reads them from (imported names bound at module level).
    monkeypatch.setattr(oauth_service, "_anthropic_refresh", fake_anthropic, raising=False)
    monkeypatch.setattr(oauth_service, "refresh_access_token", fake_openai, raising=False)

    await oauth_service._refresh_with_retry(object(), "refresh-xyz", provider=provider)

    assert (called["anthropic"] == 1) is expect_anthropic
    assert (called["openai"] == 1) is (not expect_anthropic)


# ── 2. Retry budget: transient error exhausts 3 attempts ────────────────────

async def test_refresh_exhausts_retries_on_transient_error(monkeypatch):
    """Three consecutive transient errors → DeviceFlowError(refresh_transient_exhausted)."""
    attempt_count = {"n": 0}

    async def always_fail(settings, refresh_token):
        attempt_count["n"] += 1
        raise ConnectionError("simulated transient failure")

    async def noop_sleep(*args, **kwargs):
        """Eliminate real sleep delay in the retry loop."""

    monkeypatch.setattr(oauth_service, "refresh_access_token", always_fail, raising=False)
    # _refresh_with_retry does `import asyncio as _asyncio` then `_asyncio.sleep(...)`.
    # Patching asyncio.sleep patches the same attribute looked up via the alias.
    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    with pytest.raises(DeviceFlowError):
        await oauth_service._refresh_with_retry(object(), "ref", provider="openai")

    assert attempt_count["n"] == 3  # exactly 3 attempts, then exhausted


async def test_refresh_permanent_error_propagates_immediately(monkeypatch):
    """DeviceFlowError is NOT retried — it propagates on the first attempt."""
    attempt_count = {"n": 0}

    async def permanent_fail(settings, refresh_token):
        attempt_count["n"] += 1
        raise DeviceFlowError("invalid_grant")

    monkeypatch.setattr(oauth_service, "refresh_access_token", permanent_fail, raising=False)

    with pytest.raises(DeviceFlowError, match="invalid_grant"):
        await oauth_service._refresh_with_retry(object(), "ref", provider="openai")

    assert attempt_count["n"] == 1  # no retry on permanent failure


async def test_refresh_succeeds_on_first_attempt_no_sleep(monkeypatch):
    """Happy path: no sleep, returns tokens on attempt 0."""
    slept = {"n": 0}

    async def noop_sleep(*args, **kwargs):
        slept["n"] += 1

    async def succeed(settings, refresh_token):
        return {"access_token": "fresh-acc", "refresh_token": "fresh-ref",
                "id_token": "", "expires_in": 3600}

    monkeypatch.setattr(oauth_service, "refresh_access_token", succeed, raising=False)
    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    result = await oauth_service._refresh_with_retry(object(), "old-ref", provider="openai")

    assert result["access_token"] == "fresh-acc"
    assert slept["n"] == 0  # no sleep on success


# ── 3. Crypto round-trip + nonce uniqueness ──────────────────────────────────

def test_encrypt_decrypt_round_trip_and_nonce_prefix():
    """AES-256-GCM: nonce prepended, ciphertext ≠ plaintext, decrypt recovers original."""
    blob = encrypt_secret(_SECRET, _KEY)
    # First 12 bytes are the nonce — must not be the plaintext prefix.
    assert isinstance(blob, bytes)
    assert blob[:12] != _SECRET.encode()[:12]
    assert decrypt_secret(blob, _KEY) == _SECRET


def test_encrypt_produces_unique_ciphertext_each_call():
    """Each call generates a fresh nonce → distinct ciphertext even for identical input."""
    blob1 = encrypt_secret(_SECRET, _KEY)
    blob2 = encrypt_secret(_SECRET, _KEY)
    assert blob1 != blob2


# ── 4. Decrypt-on-list: oauth rows decrypt correctly ────────────────────────

def test_decrypt_oauth_row_round_trip_with_id_token():
    """decrypt_oauth_row recovers access_token, refresh_token, and encrypted id_token."""
    key = os.urandom(32)
    expires = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    row = build_oauth_credential_row(
        tenant_id="ten_x",
        provider="anthropic",
        access_token="acc-HIDDEN-123",
        refresh_token="ref-HIDDEN-456",
        token_expires_at=expires,
        account_id="acct-x",
        created_by=None,
        master_key=key,
        id_token="eyJ-IDTOKEN-SECRET",
    )
    # id_token must be encrypted, not stored plaintext.
    assert "eyJ-IDTOKEN-SECRET" not in str(row["oauth_metadata"])
    assert "id_token_ct" in row["oauth_metadata"]

    out = decrypt_oauth_row(row, key)
    assert out["access_token"] == "acc-HIDDEN-123"
    assert out["refresh_token"] == "ref-HIDDEN-456"
    assert out["id_token"] == "eyJ-IDTOKEN-SECRET"
    assert out["account_id"] == "acct-x"


def test_oauth_metadata_blob_without_id_token():
    """oauth_metadata_blob with id_token=None produces only account_id."""
    key = os.urandom(32)
    blob = oauth_metadata_blob(account_id="acct-y", id_token=None, master_key=key)
    assert blob == {"account_id": "acct-y"}
    assert "id_token_ct" not in blob


def test_oauth_metadata_blob_with_id_token_is_encrypted_and_recoverable():
    """oauth_metadata_blob encrypts the id_token under AES-GCM; decrypt_secret recovers it."""
    key = os.urandom(32)
    id_token = "eyJ-PLAINTEXT-SECRET"
    blob = oauth_metadata_blob(account_id="acct-z", id_token=id_token, master_key=key)
    # Plaintext must not appear in the blob repr.
    assert id_token not in str(blob)
    assert "id_token_ct" in blob
    # Round-trip via raw decrypt.
    ct_bytes = base64.b64decode(blob["id_token_ct"])
    assert decrypt_secret(ct_bytes, key) == id_token


# ── 5. Credentials service fundamentals (unit-marked so -m unit coverage counts)

def test_provider_for_model_qualified_prefix():
    """Fully-qualified provider/model resolves to the prefix, not the bare table."""
    assert provider_for_model("openai/gpt-4o") == "openai"
    assert provider_for_model("anthropic/claude-3-5-sonnet") == "anthropic"


def test_provider_for_model_unknown_raises():
    with pytest.raises(ValueError, match="No known provider"):
        provider_for_model("mystery-model-9000")


def test_model_is_keyless_true_and_false():
    # Per-model rule (submit path Task 4): only free Zen models are keyless —
    # opencode-go and paid Zen models require the tenant's opencode key.
    assert model_is_keyless("opencode/deepseek-v4-flash-free") is True
    assert model_is_keyless("opencode/kimi-k2") is False
    assert model_is_keyless("opencode-go/glm-5.2") is False
    assert model_is_keyless("claude-opus-4-7") is False
    assert model_is_keyless("openai/gpt-4o") is False


def test_build_and_decrypt_api_key_row():
    key = os.urandom(32)
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key="sk-ant-xyz-1234",
        created_by="usr_1",
        master_key=key,
    )
    assert row["key_last4"] == "1234"
    assert decrypt_row(row, key) == "sk-ant-xyz-1234"


# ── 6. No-secret-leak gate: REAL credentials router output ──────────────────
#
# The gate invokes the REAL list_credentials router (GET /v1/credentials) via
# TestClient with a fake session whose rows include known secret values.
# Any regression that adds access_token / refresh_token / account_id /
# key_ciphertext to the real router projection FAILS this test.
#
# Fake session pattern: override cred_mod._session Depends with a generator
# that yields a stub connection returning seeded rows (same technique as
# tests/api_contract/test_gap_fill.py for cred_mod._session overrides).

# Known leak-marker secrets — unique strings that must NEVER appear in the
# real router output.  Chosen with a unique infix so partial matches don't
# accidentally appear elsewhere.
_ANT_ACCESS   = "sk-ant-LEAKTEST-anthropic-access-XQ9001"
_ANT_REFRESH  = "refresh-LEAKTEST-anthropic-refresh-XQ9002"
_ANT_ACCOUNT  = "acct-LEAKTEST-anthropic-acct-XQ9003"
_OAI_ACCESS   = "sk-oai-LEAKTEST-openai-access-XQ9004"
_OAI_REFRESH  = "refresh-LEAKTEST-openai-refresh-XQ9005"
_OAI_ACCOUNT  = "acct-LEAKTEST-openai-acct-XQ9006"

# The fake session returns two rows — one per provider — each carrying ALL
# secret fields that the SELECT *could* expose if someone widens the projection.
_FAKE_CRED_ROWS: list[dict[str, Any]] = [
    {
        "id": "cred_LEAKTEST_1",
        "provider": "anthropic",
        "key_last4": None,
        "auth_method": "oauth_subscription",
        "status": "active",
        # account_id stored plaintext in oauth_metadata — must not leak in full.
        "oauth_metadata": {"account_id": _ANT_ACCOUNT},
        "token_expires_at": None,
        "created_by": None,
        "created_at": None,
        # Extra secret fields that MUST be stripped by the router projection.
        # Seeding them in the row means a projection regression immediately
        # exposes them in the response and the assertion below catches it.
        "access_token": _ANT_ACCESS,
        "refresh_token": _ANT_REFRESH,
        "key_ciphertext": b"CIPHER-LEAKTEST-ant-bytes",
    },
    {
        "id": "cred_LEAKTEST_2",
        "provider": "openai",
        "key_last4": None,
        "auth_method": "oauth_subscription",
        "status": "active",
        "oauth_metadata": {"account_id": _OAI_ACCOUNT},
        "token_expires_at": None,
        "created_by": None,
        "created_at": None,
        "access_token": _OAI_ACCESS,
        "refresh_token": _OAI_REFRESH,
        "key_ciphertext": b"CIPHER-LEAKTEST-oai-bytes",
    },
]


class _LeakFakeMappings:
    """Minimal .mappings().all() / .first() stub for the fake session."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _LeakFakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _LeakFakeMappings:
        return _LeakFakeMappings(self._rows)


class _LeakConn:
    """Stub AsyncSession: execute() always returns the seeded credential rows."""

    async def execute(self, *a: Any, **k: Any) -> _LeakFakeResult:
        return _LeakFakeResult(_FAKE_CRED_ROWS)

    async def commit(self) -> None:
        pass


async def _leak_session_gen() -> AsyncIterator[_LeakConn]:
    yield _LeakConn()


def assert_no_secret_leak(response_body: Any, *secrets: str) -> None:
    """Assert none of the known secret strings appear anywhere in repr(response)."""
    blob = repr(response_body)
    for s in secrets:
        assert s not in blob, f"secret leaked into router output: {s!r}"


def test_real_list_credentials_never_leaks_tokens_or_account_id() -> None:
    """Canonical leak gate: REAL GET /v1/credentials must not return any known secret.

    Invokes the REAL list_credentials router function (not a hand-built mirror).
    Seeds the fake session with rows containing access_token, refresh_token,
    account_id (full), and key_ciphertext — all must be absent from the response.
    A regression that adds any secret field to the real projection FAILS here.
    """
    app = make_app()
    app.dependency_overrides[resolve_principal] = lambda: P_ADMIN
    app.dependency_overrides[cred_mod._session] = _leak_session_gen
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/v1/credentials")
        assert r.status_code == 200
        body = r.json()
        # Scan the REAL router JSON output for every known secret string.
        assert_no_secret_leak(
            body,
            _ANT_ACCESS,
            _ANT_REFRESH,
            _ANT_ACCOUNT,          # full account_id must not appear (only tail is allowed)
            _OAI_ACCESS,
            _OAI_REFRESH,
            _OAI_ACCOUNT,
            "CIPHER-LEAKTEST-ant-bytes",
            "CIPHER-LEAKTEST-oai-bytes",
        )
        # Sanity: account_tail (last 4 chars) IS expected to be present.
        creds = body["credentials"]
        assert len(creds) == 2
        assert creds[0]["account_tail"] == _ANT_ACCOUNT[-4:]
        assert creds[1]["account_tail"] == _OAI_ACCOUNT[-4:]
    finally:
        app.dependency_overrides.clear()


# ── 7. ensure_fresh_oauth early-exit: fresh token skips refresh ──────────────
#
# Lines ~205-215 in oauth_service.py: if token_expires_at > now + grace,
# return the stored token immediately without any DB lock or refresh call.
# This path is purely CPU — no DB session involved.

async def test_ensure_fresh_oauth_early_exit_skips_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_fresh_oauth: token fresh beyond grace → stored token returned, refresh NOT called.

    Covers oauth_service.py lines ~205-215 (the fast early-exit branch).
    Uses build_oauth_credential_row so the real decrypt_oauth_row path runs.
    The fake session passed is never touched (early exit fires before any DB call).
    """
    from control_plane.config import Settings

    key = os.urandom(32)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    # 2 hours from now > grace of 300s → early exit fires.
    far_future = now + timedelta(hours=2)

    access_val = "sk-ant-FRESHTEST-early-exit-access-001"
    refresh_val = "refresh-FRESHTEST-early-exit-refresh-001"

    row = build_oauth_credential_row(
        tenant_id="ten_x",
        provider="anthropic",
        access_token=access_val,
        refresh_token=refresh_val,
        token_expires_at=far_future,
        account_id="acct-fresh-early",
        created_by=None,
        master_key=key,
    )

    refresh_called: dict[str, int] = {"n": 0}

    async def fake_refresh_with_retry(*args: Any, **kwargs: Any) -> dict[str, Any]:
        refresh_called["n"] += 1
        return {"access_token": "MUST_NOT_APPEAR", "refresh_token": "R", "expires_in": 3600}

    monkeypatch.setattr(oauth_service, "_refresh_with_retry", fake_refresh_with_retry)

    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_1",
        seed_api_key="tk_live_test",
        seed_llm_api_key="",
        agent_image_tag="test",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
        oauth_subscription_grace_seconds=300,
    )

    # Pass a bare object() as session — early exit never touches it.
    result = await oauth_service.ensure_fresh_oauth(
        object(),  # type: ignore[arg-type]
        row,
        settings=settings,
        master_key=key,
        now=now,
    )

    assert refresh_called["n"] == 0, "refresh was called despite token being fresh"
    assert result["access_token"] == access_val
    assert result["refresh_token"] == refresh_val
    assert result["account_id"] == "acct-fresh-early"
    assert result["expires_at"] == far_future


# ── 8. Per-provider meta-gate ────────────────────────────────────────────────
#
# A new prefix-mapped provider MUST appear in _MODEL_PREFIX_PROVIDER (keyed).
# Adding a provider without classification will cause routing/credential-
# selection bugs; this gate catches it. Keyless-ness is no longer a per-
# provider property (Task 4): it is decided per-model by model_is_keyless
# (only opencode's free Zen models, ``opencode/*-free``, run without a
# credential) — a single provider like "opencode" can be both keyed (paid Zen,
# opencode-go) and keyless (free Zen) depending on the model.

def test_every_known_provider_has_a_keyed_classification():
    """Meta-gate: the real provider registry must classify anthropic and openai."""
    keyed = {p for _, p in credentials_service._MODEL_PREFIX_PROVIDER}
    assert {"anthropic", "openai"} <= keyed, (
        f"Provider registry is missing a classification. known={keyed!r}"
    )


def test_opencode_keyless_classification_is_per_model_not_per_provider():
    """opencode is keyed for paid Zen/Go models, keyless only for free Zen."""
    assert credentials_service.model_is_keyless("opencode/deepseek-v4-flash-free") is True
    assert credentials_service.model_is_keyless("opencode/kimi-k2") is False
    assert credentials_service.model_is_keyless("opencode-go/glm-5.2") is False

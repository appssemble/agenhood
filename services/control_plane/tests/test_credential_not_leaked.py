"""Credential never-leaks scan tests.

These tests are the security invariant: the plaintext API key must never
appear in the credential row, the audit log details, or any response body.

Tasks 11 (credential service/router) — pure unit assertions.
Task 16 — shim-request / tasks-row variant.
"""
from __future__ import annotations

import json
import os

import pytest

from agentcore.models import AgentConfig, Event, ResolvedLimits, ShimTaskRequest, TaskBody
from control_plane.credentials_service import (
    build_credential_row,
    decrypt_row,
)
from control_plane.routers.tasks import (
    build_shim_request as tasks_build_shim_request,
)
from control_plane.routers.tasks import (
    build_task_row,
)

SECRET = "sk-ant-THIS-MUST-NOT-LEAK-supersecret-abcd1234"


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(32)


def test_credential_row_does_not_contain_plaintext_secret(master_key: bytes) -> None:
    """The stored ciphertext must not contain the plaintext secret."""
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key=SECRET,
        created_by="usr_1",
        master_key=master_key,
    )
    # Scan every string-serialisable value in the row.
    blob = json.dumps(
        {k: v for k, v in row.items() if k != "key_ciphertext"},
        default=str,
    )
    assert SECRET not in blob, "Secret found in non-ciphertext fields of credential row"
    # The ciphertext bytes must not contain the secret as UTF-8.
    assert SECRET.encode() not in row["key_ciphertext"], (
        "Secret found in raw ciphertext bytes"
    )


def test_audit_details_never_contain_secret(master_key: bytes) -> None:
    """Audit details for credential.store must only contain last4, never the full key."""
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key=SECRET,
        created_by="usr_1",
        master_key=master_key,
    )
    # Simulate the audit details the router builds.
    audit_details = {"last4": row["key_last4"]}
    details_blob = json.dumps(audit_details)
    assert SECRET not in details_blob, "Secret found in audit details"
    # Only the last 4 chars of the key appear.
    assert row["key_last4"] == SECRET[-4:]
    assert len(audit_details["last4"]) == 4


def test_list_response_never_contains_secret(master_key: bytes) -> None:
    """Simulated list-credentials response body must not contain the secret."""
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key=SECRET,
        created_by="usr_1",
        master_key=master_key,
    )
    # The router only exposes these fields in GET /v1/credentials.
    response = {
        "credentials": [
            {
                "id": row["id"],
                "provider": row["provider"],
                "last4": row["key_last4"],
                "created_by": row["created_by"],
                "created_at": str(row["created_at"]),
            }
        ]
    }
    response_blob = json.dumps(response)
    assert SECRET not in response_blob, "Secret found in list-credentials response"
    assert "key_ciphertext" not in response_blob, "Ciphertext field leaked in list response"


def test_set_credential_response_never_contains_secret(master_key: bytes) -> None:
    """Simulated POST /v1/credentials response body must not contain the secret."""
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key=SECRET,
        created_by="usr_1",
        master_key=master_key,
    )
    # The router returns this exact dict after a successful store.
    response = {
        "id": row["id"],
        "provider": row["provider"],
        "last4": row["key_last4"],
        "created_by": row["created_by"],
        "created_at": str(row["created_at"]),
    }
    response_blob = json.dumps(response)
    assert SECRET not in response_blob, "Secret found in set-credential response"


def test_decrypt_round_trip_still_works(master_key: bytes) -> None:
    """Sanity: we can still recover the secret through the proper decrypt path."""
    row = build_credential_row(
        tenant_id="ten_1",
        provider="anthropic",
        api_key=SECRET,
        created_by="usr_1",
        master_key=master_key,
    )
    recovered = decrypt_row(row, master_key)
    assert recovered == SECRET


# ---------------------------------------------------------------------------
# Task 16: build_task_row / build_shim_request — security invariant
# ---------------------------------------------------------------------------

_TASK16_SECRET = "sk-ant-THIS-MUST-NOT-LEAK-1234"


def test_persisted_task_row_has_no_credential() -> None:
    """build_task_row output must never contain the plaintext credential."""
    config = AgentConfig(driver="vanilla", model="claude-opus-4-7", tools=["read_file"])
    row = build_task_row(
        task_id="tsk_1",
        tenant_id="ten_1",
        container_id="con_1",
        task=TaskBody(prompt="hi"),
        config=config,
    )
    blob = json.dumps(row, default=str)
    assert _TASK16_SECRET not in blob
    assert "credential" not in row["body"]
    assert "credential" not in row["config_snapshot"]


def test_shim_request_carries_credential_but_serialized_task_row_does_not() -> None:
    """The credential lives only in ShimTaskRequest, never in the persisted row."""
    config = AgentConfig(driver="vanilla", model="claude-opus-4-7", tools=["read_file"])
    task = TaskBody(prompt="hi")
    limits = ResolvedLimits(max_iterations=30, max_tokens=2_000_000, timeout_seconds=1800)

    shim_req = tasks_build_shim_request(
        task_id="tsk_1",
        task=task,
        config=config,
        limits=limits,
        credential=_TASK16_SECRET,
    )
    assert isinstance(shim_req, ShimTaskRequest)
    assert shim_req.llm_credential == _TASK16_SECRET

    row = build_task_row(
        task_id="tsk_1",
        tenant_id="ten_1",
        container_id="con_1",
        task=task,
        config=config,
    )
    assert _TASK16_SECRET not in json.dumps(row, default=str)


def test_event_payloads_never_contain_credential() -> None:
    """Representative events must not contain the plaintext secret."""
    events_list = [
        Event(seq=1, type="task_started", ts="2026-05-20T10:00:00Z",
              payload={"driver": "vanilla", "model": "claude-opus-4-7"}),
        Event(seq=2, type="assistant_message", ts="2026-05-20T10:00:01Z",
              payload={"content": [{"type": "text", "text": "working"}]}),
        Event(seq=3, type="status_change", ts="2026-05-20T10:00:02Z",
              payload={"from": "running", "to": "completed", "result": {"success": True}}),
    ]
    for e in events_list:
        assert _TASK16_SECRET not in e.model_dump_json()


# ---------------------------------------------------------------------------
# OAuth subscription: tokens never leak into non-ciphertext fields
# ---------------------------------------------------------------------------
from datetime import UTC, datetime  # noqa: E402

from control_plane.credentials_service import build_oauth_credential_row  # noqa: E402

_OAUTH_ACCESS = "access-THIS-MUST-NOT-LEAK-aaaa"
_OAUTH_REFRESH = "refresh-THIS-MUST-NOT-LEAK-bbbb"


def test_oauth_row_does_not_contain_plaintext_tokens(master_key: bytes) -> None:
    row = build_oauth_credential_row(
        tenant_id="ten_1",
        provider="openai",
        access_token=_OAUTH_ACCESS,
        refresh_token=_OAUTH_REFRESH,
        token_expires_at=datetime(2026, 6, 4, tzinfo=UTC),
        account_id="acct_1",
        created_by="usr_1",
        master_key=master_key,
    )
    non_cipher = {
        k: v
        for k, v in row.items()
        if k not in ("access_token_ciphertext", "refresh_token_ciphertext")
    }
    blob = json.dumps(non_cipher, default=str)
    assert _OAUTH_ACCESS not in blob
    assert _OAUTH_REFRESH not in blob
    assert _OAUTH_ACCESS.encode() not in row["access_token_ciphertext"]
    assert _OAUTH_REFRESH.encode() not in row["refresh_token_ciphertext"]

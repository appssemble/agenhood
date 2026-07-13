"""Unit tests for the submit-path credential resolution (opencode Go/Zen rules).

Uses a fake AsyncSession that returns canned credential rows and a monkeypatched
master key — no DB, no docker.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

import control_plane.routers.tasks as tasks_mod
from control_plane.config import Settings
from control_plane.credentials_service import build_credential_row
from control_plane.errors import APIError
from control_plane.routers.tasks import resolve_task_credential
from control_plane.schemas import AgentConfig

pytestmark = pytest.mark.unit

MASTER = os.urandom(32)
SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)


class FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """Records the provider each credential query filtered on."""

    def __init__(self, rows_by_provider: dict[str, list[dict]]):
        self.rows_by_provider = rows_by_provider
        self.queried_providers: list[str] = []

    async def execute(self, stmt: Any) -> FakeResult:
        # The credential select filters on tenant_id and provider; pull the
        # provider literal out of the compiled statement's params.
        params = stmt.compile().params
        provider = next(
            v for k, v in params.items() if k.startswith("provider")
        )
        self.queried_providers.append(provider)
        return FakeResult(self.rows_by_provider.get(provider, []))


def _config(model: str) -> AgentConfig:
    return AgentConfig(driver="opencode", model=model, tools=[])


def _key_row(provider: str, api_key: str) -> dict:
    return build_credential_row(
        tenant_id="ten_1", provider=provider, api_key=api_key,
        created_by=None, master_key=MASTER,
    )


@pytest.fixture(autouse=True)
def _master_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tasks_mod, "load_key_from_env", lambda: MASTER)


async def test_free_zen_without_key_is_keyless() -> None:
    session = FakeSession({})
    cred, kind, meta, used = await resolve_task_credential(
        session, settings=SETTINGS, tenant_id="ten_1",
        config=_config("opencode/deepseek-v4-flash-free"), timeout_seconds=600,
    )
    assert (cred, kind, meta, used) == ("", "api_key", {}, "keyless")


async def test_free_zen_with_stored_key_injects_it() -> None:
    # A stored opencode key is injected even for free models (lifts rate limits).
    session = FakeSession({"opencode": [_key_row("opencode", "oc-live-1234")]})
    cred, kind, _meta, used = await resolve_task_credential(
        session, settings=SETTINGS, tenant_id="ten_1",
        config=_config("opencode/deepseek-v4-flash-free"), timeout_seconds=600,
    )
    assert cred == "oc-live-1234"
    assert kind == "api_key"
    assert used == "api_key"


async def test_go_model_without_key_rejected() -> None:
    session = FakeSession({})
    with pytest.raises(APIError) as exc:
        await resolve_task_credential(
            session, settings=SETTINGS, tenant_id="ten_1",
            config=_config("opencode-go/glm-5.2"), timeout_seconds=600,
        )
    assert exc.value.code == "no_credential"


async def test_go_model_uses_the_opencode_credential_row() -> None:
    # opencode-go models look up the row stored under provider "opencode".
    session = FakeSession({"opencode": [_key_row("opencode", "oc-live-1234")]})
    cred, kind, _meta, used = await resolve_task_credential(
        session, settings=SETTINGS, tenant_id="ten_1",
        config=_config("opencode-go/glm-5.2"), timeout_seconds=600,
    )
    assert cred == "oc-live-1234"
    assert kind == "api_key"
    assert used == "api_key"
    assert session.queried_providers == ["opencode"]


async def test_paid_zen_without_key_rejected() -> None:
    session = FakeSession({})
    with pytest.raises(APIError) as exc:
        await resolve_task_credential(
            session, settings=SETTINGS, tenant_id="ten_1",
            config=_config("opencode/kimi-k2"), timeout_seconds=600,
        )
    assert exc.value.code == "no_credential"


async def test_anthropic_behavior_unchanged() -> None:
    session = FakeSession({"anthropic": [_key_row("anthropic", "sk-ant-9999")]})
    cred, kind, _meta, used = await resolve_task_credential(
        session, settings=SETTINGS, tenant_id="ten_1",
        config=AgentConfig(driver="vanilla", model="claude-opus-4-7", tools=["bash"]),
        timeout_seconds=600,
    )
    assert cred == "sk-ant-9999"
    assert used == "api_key"

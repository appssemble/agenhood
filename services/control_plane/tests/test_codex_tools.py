"""Codex tool toggles in the control plane."""
from __future__ import annotations

import pytest

import agentcore.drivers  # noqa: F401  registers every driver
from agentcore.models import AgentConfig

pytestmark = pytest.mark.unit

CODEX_TOOL_NAMES = ["web_search", "image_generation", "view_image", "multi_agent", "goals"]


def test_template_view_lists_codex_tool_specs():
    from control_plane.routers.templates import template_public_view

    view = template_public_view({"driver": "codex"})
    assert [s["name"] for s in view["available_tool_specs"]] == CODEX_TOOL_NAMES
    assert view["driver_template"]["default_tools"] == ["web_search"]
    assert view["driver_template"]["tools_user_editable"] is True


def test_template_view_vanilla_unchanged():
    from agentcore.drivers.base import DRIVERS
    from control_plane.routers.templates import template_public_view

    view = template_public_view({"driver": "vanilla"})
    names = [s["name"] for s in view["available_tool_specs"]]
    assert names == DRIVERS["vanilla"].default_template.available_tools


def test_seed_codex_builtin_starts_with_web_search_only():
    from control_plane.seed import build_builtin_template_rows

    rows = {r["driver"]: r for r in build_builtin_template_rows()}
    assert rows["codex"]["tools"] == ["web_search"]
    assert rows["claude-code"]["tools"] == []


def test_seed_vanilla_builtin_keeps_all_tools():
    from agentcore.drivers.base import DRIVERS
    from control_plane.seed import build_builtin_template_rows

    rows = {r["driver"]: r for r in build_builtin_template_rows()}
    assert rows["vanilla"]["tools"] == DRIVERS["vanilla"].default_template.available_tools


def test_codex_tools_pass_slim_variant_check():
    from agentcore.drivers.base import DRIVERS
    from agentcore.tools.base import TOOLS
    from control_plane.variants import assert_config_runnable_on_variant

    assert_config_runnable_on_variant(
        variant="slim", driver_name="codex", tool_names=CODEX_TOOL_NAMES,
        drivers=DRIVERS, tools=TOOLS,
    )


def _codex(**kw):
    return AgentConfig(driver="codex", model="gpt-5.4", **kw)


def test_default_tools_for():
    from control_plane.config_validation import default_tools_for

    assert default_tools_for("codex") == ["web_search"]
    assert default_tools_for("vanilla") is None
    assert default_tools_for("nope") is None


def test_fill_default_tools_when_omitted():
    from control_plane.config_validation import fill_default_tools

    assert fill_default_tools(_codex(), tools_given=False).tools == ["web_search"]


def test_fill_default_tools_keeps_explicit_empty():
    from control_plane.config_validation import fill_default_tools

    cfg = _codex(tools=[])
    assert fill_default_tools(cfg, tools_given=True) is cfg


def test_fill_default_tools_leaves_vanilla_empty():
    from control_plane.config_validation import fill_default_tools

    cfg = AgentConfig(driver="vanilla", model="m")
    assert fill_default_tools(cfg, tools_given=False).tools == []


def test_config_patch_without_tools_keeps_web_search():
    from control_plane.config_validation import fill_default_tools
    from control_plane.schemas import ConfigPatch

    patch = ConfigPatch(driver="codex", model="gpt-5.4")
    cfg = fill_default_tools(
        patch.to_agent_config(), tools_given="tools" in patch.model_fields_set
    )
    assert cfg.tools == ["web_search"]


def test_config_patch_with_empty_tools_turns_all_off():
    from control_plane.config_validation import fill_default_tools
    from control_plane.schemas import ConfigPatch

    patch = ConfigPatch(driver="codex", model="gpt-5.4", tools=[])
    cfg = fill_default_tools(
        patch.to_agent_config(), tools_given="tools" in patch.model_fields_set
    )
    assert cfg.tools == []


LIMITS = {"allowed_drivers": ["vanilla", "opencode", "claude-code", "codex"]}


def test_validate_config_accepts_codex_tools():
    from control_plane.config_validation import validate_config

    validate_config(
        AgentConfig(driver="codex", model="gpt-5.5", tools=CODEX_TOOL_NAMES), LIMITS
    )  # must not raise


def test_validate_config_rejects_unknown_codex_tool():
    from control_plane.config_validation import validate_config
    from control_plane.errors import APIError

    with pytest.raises(APIError) as exc:
        validate_config(AgentConfig(driver="codex", model="gpt-5.5", tools=["bash"]), LIMITS)
    assert exc.value.field == "tools"


# ---------------------------------------------------------------------------
# Router/function-level coverage: the real call sites, not just the helpers.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402


def test_resolve_create_config_inline_codex_without_tools_gets_web_search():
    from control_plane.routers.containers import _resolve_create_config
    from control_plane.schemas import CreateContainerRequest

    req = CreateContainerRequest(name="c", config=_codex())
    cfg, template_id, _rt = asyncio.run(_resolve_create_config(None, req))
    assert cfg.tools == ["web_search"]
    assert template_id is None


def test_resolve_create_config_inline_codex_explicit_empty_tools_stays_off():
    from control_plane.routers.containers import _resolve_create_config
    from control_plane.schemas import CreateContainerRequest

    req = CreateContainerRequest(name="c", config=_codex(tools=[]))
    cfg, _tid, _rt = asyncio.run(_resolve_create_config(None, req))
    assert cfg.tools == []


def test_resolve_create_config_inline_vanilla_without_tools_stays_empty():
    from control_plane.routers.containers import _resolve_create_config
    from control_plane.schemas import CreateContainerRequest

    req = CreateContainerRequest(name="c", config=AgentConfig(driver="vanilla", model="m"))
    cfg, _tid, _rt = asyncio.run(_resolve_create_config(None, req))
    assert cfg.tools == []


# --- template create/patch, through the real router (TestClient, no DB) -----

from fastapi.testclient import TestClient  # noqa: E402

from control_plane.app import create_app  # noqa: E402
from control_plane.auth.principal import Principal, resolve_principal  # noqa: E402
from control_plane.config import Settings  # noqa: E402

_TPL_SETTINGS = Settings(
    database_url="postgresql+asyncpg://x:x@localhost/x",
    seed_tenant_id="ten_seed",
    seed_api_key="tk_live_seed",
    seed_llm_api_key="",
    agent_image_tag="test",
    internal_network="test",
    readyz_timeout_seconds=1.0,
    shim_port=8080,
)

_tpl_app = create_app(_TPL_SETTINGS)
_ADMIN = Principal(tenant_id="ten_1", role="admin", is_staff=False, user_id="usr_a")


class _TplResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _TplSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *a, **k):
        return _TplResult(self._rows)

    async def commit(self):
        return None


def _tpl_row(**over):
    class _R:
        _mapping = {
            "id": "tpl_1", "tenant_id": "ten_1", "name": "T", "driver": "codex",
            "model": "gpt-5.4", "system_prompt": "", "system_prompt_mode": "augment",
            "tools": ["view_image"], "context": {}, "skills": [], "mcp_servers": [],
            "limits": {}, "is_builtin": False, "created_by": "u",
            "image_variant": None, "mem_limit": None, "cpus": None,
            **over,
        }
    return _R()


def _use_tpl(rows=None):
    _tpl_app.dependency_overrides[resolve_principal] = lambda: _ADMIN
    _tpl_app.state.session_factory = lambda: _TplSession(rows or [])


def teardown_function():
    _tpl_app.dependency_overrides.clear()


def test_create_template_codex_without_tools_gets_web_search():
    _use_tpl()
    with TestClient(_tpl_app) as c:
        r = c.post("/v1/templates", json={"name": "T", "driver": "codex"})
    assert r.status_code == 200
    assert r.json()["tools"] == ["web_search"]


def test_patch_template_same_driver_resend_keeps_customized_tools():
    # Regression: PATCHing a codex template with its own driver (tools omitted)
    # must not overwrite a customized tool set with the driver defaults.
    _use_tpl(rows=[_tpl_row(tools=["view_image"])])
    with TestClient(_tpl_app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"driver": "codex"})
    assert r.status_code == 200
    assert r.json()["tools"] == ["view_image"]


def test_patch_template_driver_change_to_codex_without_tools_gets_web_search():
    _use_tpl(rows=[_tpl_row(driver="vanilla", tools=[])])
    with TestClient(_tpl_app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"driver": "codex"})
    assert r.status_code == 200
    assert r.json()["tools"] == ["web_search"]


def test_patch_template_driver_change_with_tools_sent_keeps_sent():
    _use_tpl(rows=[_tpl_row(driver="vanilla", tools=[])])
    with TestClient(_tpl_app) as c:
        r = c.patch(
            "/v1/templates/tpl_1", json={"driver": "codex", "tools": ["goals"]}
        )
    assert r.status_code == 200
    assert r.json()["tools"] == ["goals"]


def test_patch_template_driver_change_to_vanilla_without_tools_keeps_stored():
    _use_tpl(rows=[_tpl_row(driver="codex", tools=["view_image"])])
    with TestClient(_tpl_app) as c:
        r = c.patch("/v1/templates/tpl_1", json={"driver": "vanilla"})
    assert r.status_code == 200
    assert r.json()["tools"] == ["view_image"]

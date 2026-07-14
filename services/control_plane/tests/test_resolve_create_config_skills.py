"""When a container is created from a template, the template's skills must flow
into the container's AgentConfig (templates redesign spec §3)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from control_plane.routers.containers import _resolve_create_config
from control_plane.schemas import CreateContainerRequest

pytestmark = pytest.mark.unit


class _Row:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _Session:
    def __init__(self, row: Any) -> None:
        self._row = row

    async def execute(self, *a: Any, **k: Any) -> _Result:
        return _Result(self._row)


def test_template_skills_flow_into_config() -> None:
    row = _Row(
        id="tpl_1", driver="opencode", model="claude-sonnet-4-6", effort=None,
        system_prompt="", system_prompt_mode="augment",
        tools=[], context={}, skills=["skl_1", "skl_2"], mcp_servers=[],
        image_variant=None, mem_limit=None, cpus=None, env_vars=None,
    )
    req = CreateContainerRequest(name="c", template_id="tpl_1")
    cfg, tid, _tpl_runtime = asyncio.run(_resolve_create_config(_Session(row), req))
    assert tid == "tpl_1"
    assert cfg.skills == ["skl_1", "skl_2"]


def test_template_mcp_servers_flow_into_config() -> None:
    """Template mcp_servers propagate into the resolved AgentConfig (Fix A4)."""
    row = _Row(
        id="tpl_1", driver="opencode", model="claude-sonnet-4-6", effort=None,
        system_prompt="", system_prompt_mode="augment",
        tools=[], context={}, skills=[], mcp_servers=["mcp_1"],
        image_variant=None, mem_limit=None, cpus=None, env_vars=None,
    )
    req = CreateContainerRequest(name="c", template_id="tpl_1")
    cfg, tid, _tpl_runtime = asyncio.run(_resolve_create_config(_Session(row), req))
    assert tid == "tpl_1"
    assert cfg.mcp_servers == ["mcp_1"]


def test_template_effort_flows_into_config() -> None:
    row = _Row(
        id="tpl_1", driver="codex", model="gpt-5.4", effort="high",
        system_prompt="", system_prompt_mode="augment",
        tools=[], context={}, skills=[], mcp_servers=[],
        image_variant=None, mem_limit=None, cpus=None, env_vars=None,
    )
    req = CreateContainerRequest(name="c", template_id="tpl_1")
    cfg, _tid, _tpl_runtime = asyncio.run(_resolve_create_config(_Session(row), req))
    assert cfg.effort == "high"


def test_template_without_effort_is_valid() -> None:
    row = _Row(
        id="tpl_1", driver="codex", model="gpt-5.4", effort=None,
        system_prompt="", system_prompt_mode="augment",
        tools=[], context={}, skills=[], mcp_servers=[],
        image_variant=None, mem_limit=None, cpus=None, env_vars=None,
    )
    req = CreateContainerRequest(name="c", template_id="tpl_1")
    cfg, _tid, _tpl_runtime = asyncio.run(_resolve_create_config(_Session(row), req))
    assert cfg.effort is None

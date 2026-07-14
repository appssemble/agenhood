from __future__ import annotations

import os

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from control_plane.env_vars import store_env_vars
from control_plane.routers.tasks import build_shim_request, build_task_row

pytestmark = pytest.mark.unit

_KEY = os.urandom(32)


def _cfg() -> AgentConfig:
    return AgentConfig(driver="vanilla", model="m")


def test_build_shim_request_carries_env() -> None:
    req = build_shim_request(
        task_id="tsk_1", task=TaskBody(prompt="p"), config=_cfg(),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        credential="", env={"FOO": "bar"},
    )
    assert req.env == {"FOO": "bar"}


def test_build_shim_request_env_default_empty() -> None:
    req = build_shim_request(
        task_id="tsk_1", task=TaskBody(prompt="p"), config=_cfg(),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=1),
        credential="",
    )
    assert req.env == {}


def test_task_row_never_contains_env() -> None:
    # config_snapshot is persisted; env values must not appear anywhere in it.
    row = build_task_row(
        task_id="tsk_1", tenant_id="ten_1", container_id="ctr_1",
        task=TaskBody(prompt="p"), config=_cfg(),
    )
    assert "env" not in row["config_snapshot"]
    assert "env" not in row


def test_resolve_env_round_trip_matches_dispatch_shape() -> None:
    from control_plane.env_vars import resolve_env
    stored = store_env_vars(
        [{"name": "KEY", "value": "s3cret", "secret": True}], None, lambda: _KEY
    )
    assert resolve_env(stored, lambda: _KEY) == {"KEY": "s3cret"}

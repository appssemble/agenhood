# services/control_plane/tests/test_task_skills.py
from __future__ import annotations

import pytest

from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from control_plane.routers.tasks import build_shim_request, build_task_skills

pytestmark = pytest.mark.unit


def _rows():
    return [
        {"id": "skl_a", "name": "a", "description": "da", "body": "ba", "enabled": True},
        {"id": "skl_b", "name": "b", "description": "db", "body": "bb", "enabled": True},
    ]


def test_build_task_skills_only_for_opencode() -> None:
    cfg = AgentConfig(driver="vanilla", model="m", skills=["skl_a"])
    assert build_task_skills(cfg, _rows()) == []


def test_build_task_skills_resolves_for_opencode() -> None:
    cfg = AgentConfig(driver="opencode", model="m", skills=["skl_b", "skl_a"])
    out = build_task_skills(cfg, _rows())
    assert [s.name for s in out] == ["b", "a"]


def test_build_task_skills_empty_when_none_selected() -> None:
    cfg = AgentConfig(driver="opencode", model="m", skills=[])
    assert build_task_skills(cfg, _rows()) == []


def test_build_task_skills_resolves_for_codex() -> None:
    cfg = AgentConfig(driver="codex", model="m", skills=["skl_b", "skl_a"])
    out = build_task_skills(cfg, _rows())
    assert [s.name for s in out] == ["b", "a"]


def test_build_task_skills_still_empty_for_vanilla() -> None:
    cfg = AgentConfig(driver="vanilla", model="m", skills=["skl_a"])
    assert build_task_skills(cfg, _rows()) == []


def test_build_task_skills_ships_git_bundle() -> None:
    import base64

    config = AgentConfig(driver="opencode", model="anthropic/claude-x",
                         skills=["b"])
    rows = [
        {"id": "b", "name": "pdf", "description": "d", "body": "",
         "enabled": True, "source_type": "git", "bundle": b"gz",
         "bundle_size": 2},
    ]
    out = build_task_skills(config, rows)
    assert out[0].bundle_b64 == base64.b64encode(b"gz").decode()


def test_shim_request_carries_skills_but_task_row_never_does() -> None:
    from control_plane.routers.tasks import build_task_row

    task = TaskBody(prompt="hi")
    config = AgentConfig(driver="opencode", model="m", skills=["skl_a"])
    limits = ResolvedLimits(max_iterations=5, max_tokens=100, timeout_seconds=30)
    skills = build_task_skills(config, _rows())
    req = build_shim_request(
        task_id="tsk_1", task=task, config=config, limits=limits,
        credential="sk", skills=skills,
    )
    assert [s.name for s in req.skills] == ["a"]
    row = build_task_row(
        task_id="tsk_1", tenant_id="t", container_id="c", task=task, config=config
    )
    # the resolved skill body never reaches the persisted task row; only the
    # selected ids live in config_snapshot.
    assert "ba" not in str(row)
    assert row["config_snapshot"]["skills"] == ["skl_a"]

from __future__ import annotations

import pytest

from agentcore.models import AgentConfig, ShimSkill, ShimTaskRequest

pytestmark = pytest.mark.unit


def _req_kwargs() -> dict:
    return {
        "task_id": "tsk_1",
        "task": {"prompt": "hi"},
        "config": {"driver": "opencode", "model": "claude-sonnet-4-6"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk-secret",
    }


def test_agent_config_skills_defaults_to_empty() -> None:
    cfg = AgentConfig(driver="opencode", model="m")
    assert cfg.skills == []


def test_agent_config_accepts_skill_ids() -> None:
    cfg = AgentConfig(driver="opencode", model="m", skills=["skl_a", "skl_b"])
    assert cfg.skills == ["skl_a", "skl_b"]


def test_shim_request_skills_defaults_to_empty() -> None:
    req = ShimTaskRequest.model_validate(_req_kwargs())
    assert req.skills == []


def test_shim_request_accepts_resolved_skills() -> None:
    body = _req_kwargs()
    body["skills"] = [{"name": "git-release", "description": "Make releases", "body": "# do it"}]
    req = ShimTaskRequest.model_validate(body)
    assert isinstance(req.skills[0], ShimSkill)
    assert req.skills[0].name == "git-release"
    assert req.skills[0].body == "# do it"


def test_shimskill_bundle_b64_defaults_none() -> None:
    from agentcore.models import ShimSkill
    s = ShimSkill(name="x", description="d")
    assert s.bundle_b64 is None
    assert s.body == ""


def test_shimskill_accepts_bundle_b64() -> None:
    from agentcore.models import ShimSkill
    s = ShimSkill(name="x", description="d", bundle_b64="QUJD")
    assert s.bundle_b64 == "QUJD"

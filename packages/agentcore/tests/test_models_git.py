# packages/agentcore/tests/test_models_git.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentcore.models import Event, GitPushConfig, ShimTaskRequest

pytestmark = pytest.mark.unit


def _req_kwargs() -> dict:
    return {
        "task_id": "tsk_1",
        "task": {"prompt": "hi"},
        "config": {"driver": "vanilla", "model": "m"},
        "limits": {"max_iterations": 5, "max_tokens": 1000, "timeout_seconds": 30},
        "llm_credential": "sk-secret",
    }


def test_shim_request_git_push_defaults_to_none() -> None:
    req = ShimTaskRequest.model_validate(_req_kwargs())
    assert req.git_push is None


def test_shim_request_accepts_git_push_block() -> None:
    body = _req_kwargs()
    body["git_push"] = {"url": "git@github.com:acme/repo.git", "ssh_private_key": "KEY"}
    req = ShimTaskRequest.model_validate(body)
    assert isinstance(req.git_push, GitPushConfig)
    assert req.git_push.branch == "main"          # default branch
    assert req.git_push.ssh_private_key == "KEY"


def test_git_is_a_valid_event_type() -> None:
    ev = Event(seq=1, type="git", ts=datetime.now(UTC),
               payload={"op": "push", "ok": True})
    assert ev.type == "git"

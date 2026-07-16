from __future__ import annotations

import pytest

from control_plane.config import Settings

pytestmark = pytest.mark.unit

_VARS = (
    "AGENT_IMAGE_PULL_POLICY",
    "IMAGE_PREPULL_INTERVAL_SECONDS",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
)


def test_provisioning_defaults(monkeypatch):
    for k in _VARS:
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.agent_image_pull_policy == "if-not-present"
    assert s.image_prepull_interval_seconds == 600
    assert s.db_pool_size == 10
    assert s.db_max_overflow == 20


def test_provisioning_overrides(monkeypatch):
    monkeypatch.setenv("AGENT_IMAGE_PULL_POLICY", "always")
    monkeypatch.setenv("IMAGE_PREPULL_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "13")
    s = Settings.from_env()
    assert s.agent_image_pull_policy == "always"
    assert s.image_prepull_interval_seconds == 120
    assert s.db_pool_size == 7
    assert s.db_max_overflow == 13


def test_invalid_pull_policy_fails_fast(monkeypatch):
    monkeypatch.setenv("AGENT_IMAGE_PULL_POLICY", "sometimes")
    with pytest.raises(ValueError, match="AGENT_IMAGE_PULL_POLICY"):
        Settings.from_env()

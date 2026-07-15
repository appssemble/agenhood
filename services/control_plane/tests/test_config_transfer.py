"""WORKFLOW_TRANSFER_MAX_BYTES: default + env override (add-env-config pattern)."""
from __future__ import annotations

import pytest

from control_plane.config import Settings

pytestmark = pytest.mark.unit


def test_transfer_max_bytes_default(monkeypatch):
    monkeypatch.delenv("WORKFLOW_TRANSFER_MAX_BYTES", raising=False)
    s = Settings.from_env()
    assert s.workflow_transfer_max_bytes == 524288000


def test_transfer_max_bytes_env_override(monkeypatch):
    monkeypatch.setenv("WORKFLOW_TRANSFER_MAX_BYTES", "1048576")
    s = Settings.from_env()
    assert s.workflow_transfer_max_bytes == 1048576

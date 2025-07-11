"""Prove the integration-skip harness works correctly.

* ``test_plain_runs_always`` has no marker; the root conftest auto-adds ``unit``,
  so ``pytest -m unit`` selects it.
* ``test_integration_marker_runs_only_with_docker`` is marked ``integration``; it
  is skipped when no docker daemon is reachable, or passes when one is present.
"""

from __future__ import annotations

import importlib

import pytest

# Prefer a direct import from the root conftest; fall back to importlib when the
# root isn't on sys.path (e.g. some IDE runners).
try:
    from conftest import DOCKER_AVAILABLE
except ImportError:
    DOCKER_AVAILABLE = importlib.import_module("conftest").DOCKER_AVAILABLE


def test_plain_runs_always() -> None:
    """An unmarked test: auto-marked 'unit' by the root conftest hook."""
    assert True


@pytest.mark.integration
def test_integration_marker_runs_only_with_docker() -> None:
    """Skipped when docker is absent; passes (body runs) when docker is present."""
    assert DOCKER_AVAILABLE is True

"""Root test configuration: auto-mark and auto-skip integration tests.

Applied to ALL testpaths (agentcore + services) because this file lives at the
repo root.

Behaviour
---------
* Any test item that does **not** carry the ``integration`` marker is
  automatically given the ``unit`` marker, so ``pytest -m unit`` collects every
  non-integration test and ``pytest -m integration`` collects only integration
  tests.

* A test marked ``@pytest.mark.integration`` requires a reachable docker daemon.
  When none is present (CI unit job, laptops without docker) those tests are
  *skipped* rather than failed, so ``pytest -m unit`` and a bare ``pytest`` run
  cleanly anywhere (index §8: "Integration tests skip cleanly when no docker
  daemon is present").

  Set ``REQUIRE_DOCKER=1`` in the environment to turn skips back into hard
  failures so a misconfigured CI runner fails loudly.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        result = subprocess.run(
            [docker, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# Computed once per session (a daemon check is comparatively expensive).
DOCKER_AVAILABLE = _docker_available()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    # Step a: auto-mark any test without 'integration' as 'unit'.
    for item in items:
        if "integration" not in item.keywords:
            item.add_marker(pytest.mark.unit)

    # Step b: skip integration tests when no docker daemon is reachable,
    # unless the caller explicitly requires docker (CI integration job).
    if DOCKER_AVAILABLE:
        return
    if os.environ.get("REQUIRE_DOCKER") == "1":
        return
    skip = pytest.mark.skip(reason="no docker daemon available")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)

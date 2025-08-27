import shutil
import subprocess

import pytest


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_or_skip():
    if not _docker_available():
        pytest.skip("docker daemon not available")

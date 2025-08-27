# services/shim/tests/integration/container/conftest.py
import pathlib
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

ROOT = pathlib.Path(__file__).resolve().parents[5]  # monorepo root
COMPOSE = ["docker", "compose", "-f",
           str(ROOT / "deploy/docker-compose.shim-it.yml")]
BASE = "http://localhost:8080"
TOKEN = "test-shim-token"


@pytest.fixture(scope="module")
def stack(docker_or_skip):
    subprocess.run(["make", "-C", str(ROOT / "images/agent"), "image"], check=True)
    subprocess.run(COMPOSE + ["up", "-d", "--build"], check=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        subprocess.run(COMPOSE + ["logs"], check=False)
        subprocess.run(COMPOSE + ["down", "-v"], check=False)
        pytest.fail("shim never became healthy")
    yield COMPOSE
    subprocess.run(COMPOSE + ["down", "-v"], check=False)


@pytest.fixture()
def client(stack):
    with httpx.Client(base_url=BASE, timeout=15,
                      headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c

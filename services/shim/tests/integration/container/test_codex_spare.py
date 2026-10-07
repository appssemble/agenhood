import json
import time

import httpx
import pytest

from . import scripting as sc
from .conftest import BASE, TOKEN

pytestmark = pytest.mark.integration

HDR = {"Authorization": f"Bearer {TOKEN}"}


def spare_outcomes(task_id):
    sse = httpx.get(f"{BASE}/tasks/{task_id}/events", headers=HDR, timeout=10)
    out = []
    for line in sse.text.splitlines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[len("data: "):])
        payload = event["payload"]
        if event["type"] == "log" and payload.get("op") == "codex_spare":
            out.append(payload.get("outcome"))
    return out


def test_second_codex_task_claims_the_spare(client):
    turns = [{"done": {"success": True, "output": "ok"}}]
    first = sc.task_body("tsk_spare_1", "codex", turns=turns)
    assert client.post("/tasks", json=first).status_code == 200
    assert sc.poll_terminal(client, "tsk_spare_1")["status"] == "completed"
    time.sleep(2)

    second = sc.task_body("tsk_spare_2", "codex", turns=turns)
    assert client.post("/tasks", json=second).status_code == 200
    assert sc.poll_terminal(client, "tsk_spare_2")["status"] == "completed"

    assert spare_outcomes("tsk_spare_1") == ["miss"]
    assert spare_outcomes("tsk_spare_2") == ["hit"]

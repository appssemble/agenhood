# services/shim/tests/integration/container/scripting.py
"""Build @@SCRIPT@@ task payloads and poll the shim for terminal status."""
from __future__ import annotations

import json
import time
from typing import Any

TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def script_prompt(*, turns=None, **flags) -> str:
    script: dict[str, Any] = {"turns": turns or []}
    for key in ("usage", "delay_ms", "http_error", "malformed", "never_done"):
        if key in flags and flags[key] is not None:
            script[key] = flags[key]
    return "Run the scripted task.\n@@SCRIPT@@ " + json.dumps(script)


def task_body(task_id, driver, *, turns=None, output=None, tools=None,
              limits=None, **flags) -> dict:
    return {
        "task_id": task_id,
        "task": {
            "prompt": script_prompt(turns=turns, **flags),
            "output": output or {"type": "text"},
        },
        "config": {"driver": driver, "model": "stub-model",
                   "tools": tools if tools is not None
                   else ["write_file", "read_file", "list_files"]},
        "limits": limits or {"max_iterations": 8, "max_tokens": 1_000_000,
                             "timeout_seconds": 30},
        "llm_credential": "sk-stub",
    }


def poll_terminal(client, task_id, timeout=30) -> dict:
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get(f"/tasks/{task_id}").json()
        if status["status"] in TERMINAL:
            return status
        time.sleep(0.3)
    raise AssertionError(f"task {task_id} never reached terminal: {status}")

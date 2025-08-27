from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

from agentcore.models import Event

RUNTIME_DIR = ".agent-runtime"


class EventLog:
    """Append-only .jsonl event log for one task, plus a task-index json.

    seq is monotonic per task starting at 1, and survives process restarts by
    resuming the counter from the existing file.
    """

    def __init__(self, workspace: str, task_id: str) -> None:
        self._task_id = task_id
        base = os.path.join(workspace, RUNTIME_DIR)
        self._events_path = os.path.join(base, "events", f"{task_id}.jsonl")
        self._index_path = os.path.join(base, "tasks", f"{task_id}.json")
        os.makedirs(os.path.dirname(self._events_path), exist_ok=True)
        os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
        self._lock = threading.Lock()
        self._seq = self._last_seq_on_disk()

    def _last_seq_on_disk(self) -> int:
        if not os.path.exists(self._events_path):
            return 0
        last = 0
        with open(self._events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = json.loads(line)["seq"]
        return last

    def append(self, event_type: str, payload: dict[str, Any]) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(
                seq=self._seq,
                type=event_type,
                ts=datetime.now(UTC),
                payload=payload,
            )
            line = json.dumps(
                {
                    "task_id": self._task_id,
                    "seq": event.seq,
                    "type": event.type,
                    "ts": event.ts.isoformat(),
                    "payload": event.payload,
                }
            )
            with open(self._events_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return event

    def read_all(self) -> list[Event]:
        return self.read_after(0)

    def read_after(self, after_seq: int) -> list[Event]:
        if not os.path.exists(self._events_path):
            return []
        out: list[Event] = []
        with open(self._events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj["seq"] <= after_seq:
                    continue
                out.append(
                    Event(
                        seq=obj["seq"],
                        type=obj["type"],
                        ts=datetime.fromisoformat(obj["ts"]),
                        payload=obj["payload"],
                    )
                )
        return out

    def write_status(self, status_obj: dict[str, Any]) -> None:
        with self._lock:
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(status_obj, f)

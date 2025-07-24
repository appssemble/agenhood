from __future__ import annotations

import dataclasses
import difflib
import json
import os
from pathlib import Path
from typing import Any

_GOLDEN_DIR = Path(__file__).parents[1] / "golden"


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if hasattr(value, "model_dump"):  # pydantic BaseModel
        return to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _serialize(value: Any, subs: dict[str, str] | None) -> str:
    text = json.dumps(to_jsonable(value), indent=2, sort_keys=True)
    for raw, placeholder in (subs or {}).items():
        if raw:
            text = text.replace(raw, placeholder)
    return text + "\n"


def golden(name: str, value: Any, *, subs: dict[str, str] | None = None) -> None:
    path = _GOLDEN_DIR / f"{name}.json"
    actual = _serialize(value, subs)
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
        return
    if not path.exists():
        raise AssertionError(
            f"missing golden {path}. Inspect the value, then regenerate with "
            f"UPDATE_GOLDEN=1 and review the committed diff."
        )
    expected = path.read_text()
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"{name} (golden)",
                tofile=f"{name} (actual)",
            )
        )
        raise AssertionError(f"golden mismatch for {name}:\n{diff}")

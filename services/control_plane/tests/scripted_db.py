from __future__ import annotations

from typing import Any


class ScriptedResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows

    def mappings(self) -> ScriptedMappings:
        return ScriptedMappings(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class ScriptedMappings:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class ScriptedSession:
    """Async fake DB session returning scripted execute results in sequence."""

    def __init__(self, query_results: list[Any] | None = None) -> None:
        self._results = list(query_results or [])
        self._idx = 0

    async def __aenter__(self) -> ScriptedSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, *_a: Any, **_k: Any) -> ScriptedResult:
        if self._idx < len(self._results):
            val = self._results[self._idx]
            self._idx += 1
            if isinstance(val, list):
                return ScriptedResult(val)
            return ScriptedResult([val] if val is not None else [])
        return ScriptedResult([])

    async def commit(self) -> None:
        return None

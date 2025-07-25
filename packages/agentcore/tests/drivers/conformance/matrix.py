# packages/agentcore/tests/drivers/conformance/matrix.py
from __future__ import annotations

import asyncio
import dataclasses
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agentcore.drivers.claude_code import ClaudeCodeDriver
from agentcore.drivers.codex import CodexDriver
from agentcore.drivers.opencode import OpencodeDriver
from agentcore.drivers.vanilla import VanillaDriver
from agentcore.llm.base import LLMResponse
from agentcore.models import AgentConfig, ResolvedLimits, TaskBody
from tests.drivers.conformance.fakes import (
    CRED,
    SUBS,  # noqa: F401 – re-exported; test_conformance accesses as M.SUBS
    FakeProc,
    ScriptedLLM,
    collector,
    patch_proc,
)
from tests.drivers.conformance.golden_helper import golden, to_jsonable


@dataclasses.dataclass(frozen=True)
class DriverEntry:
    name: str
    instance: object
    subprocess: bool


ALL_DRIVERS: list[DriverEntry] = [
    DriverEntry("vanilla", VanillaDriver(llm=ScriptedLLM([])), subprocess=False),
    DriverEntry("opencode", OpencodeDriver(), subprocess=True),
    DriverEntry("codex", CodexDriver(), subprocess=True),
    DriverEntry("claude-code", ClaudeCodeDriver(), subprocess=True),
]


@dataclasses.dataclass(frozen=True)
class Scenario:
    id: str
    applies_to: str  # "all" | "subprocess_only"
    run: Callable[[DriverEntry], None]


def applies(scenario: Scenario, entry: DriverEntry) -> bool:
    if scenario.applies_to == "all":
        return True
    return entry.subprocess


def _metadata(entry: DriverEntry) -> None:
    drv = entry.instance
    value = {
        "name": drv.name,
        "capabilities": drv.capabilities,
        "default_template": drv.default_template,
    }
    golden(f"{entry.name}/metadata", value)


SCENARIOS: list[Scenario] = [
    Scenario("metadata", "all", _metadata),
]


# ---------------------------------------------------------------------------
# Event-stream scenario helpers
# ---------------------------------------------------------------------------

_CORPUS = Path(__file__).parents[1] / "corpus"

# max_iterations=2 keeps vanilla-error golden compact (2 nudge loops → limit).
_LIMITS = ResolvedLimits(max_iterations=2, max_tokens=100_000, timeout_seconds=30)


def _case_file(case: str) -> str:
    """Map a parametrize case name to the corpus filename stem."""
    return "success_with_usage" if case == "success" else case


def _vanilla_script(case: str) -> list:
    """Build the ScriptedLLM response list mirroring the corpus intent."""
    if case == "success":
        return [
            LLMResponse(
                content=[
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "done",
                        "input": {"success": True, "output": "all done"},
                    }
                ],
                tokens_in=10,
                tokens_out=3,
                stop_reason="tool_use",
            ),
        ]
    if case == "error":
        # Empty script → ScriptedLLM returns default text turns → hits
        # iteration_limit after max_iterations=2 loops → status_change failed.
        return []
    if case == "multi_step":
        # Text turn (nudge) then done — exercises the 2-iteration path and
        # cumulative token_update (mirrors opencode/codex multi_step intent).
        return [
            LLMResponse(
                content=[{"type": "text", "text": "thinking..."}],
                tokens_in=5,
                tokens_out=2,
                stop_reason="end_turn",
            ),
            LLMResponse(
                content=[
                    {
                        "type": "tool_use",
                        "id": "tu2",
                        "name": "done",
                        "input": {"success": True, "output": "all done"},
                    }
                ],
                tokens_in=10,
                tokens_out=3,
                stop_reason="tool_use",
            ),
        ]
    raise ValueError(f"unknown vanilla case: {case!r}")


def to_jsonable_events(events: list) -> Any:
    """Convert an event list to a JSON-serialisable form (reuses golden_helper)."""
    return to_jsonable(events)


def _patch_proc_missing_binary(monkeypatch: object) -> None:
    """Patch spawn_untrusted to raise FileNotFoundError (missing-binary scenario)."""

    async def _raise_fnf(argv: list, *, cwd: str, env: dict, **kwargs: Any) -> None:
        raise FileNotFoundError("binary not found")

    monkeypatch.setattr("agentcore.sandbox.spawn_untrusted", _raise_fnf)  # type: ignore[attr-defined]
    monkeypatch.setattr("agentcore.sandbox.ensure_agent_dir", lambda *a, **kw: None)  # type: ignore[attr-defined]


def _events_for(
    entry: DriverEntry, case: str, monkeypatch: object
) -> tuple[list, str]:
    """Drive ``entry.instance.run(...)`` for ``case`` and return (events, workspace).

    Subprocess drivers replay the corpus file via FakeProc; vanilla gets a
    ScriptedLLM scripted to mirror the corpus intent.  ``case`` is the
    parametrize name ("success", "error", "multi_step", "cancel", "timeout",
    "missing_binary"); corpus filenames map via ``_case_file`` (success →
    success_with_usage).
    """
    events, emit = collector()
    ws = tempfile.mkdtemp()
    cfg = AgentConfig(driver=entry.name, model="m-test")

    # ------------------------------------------------------------------
    # Loop-invariant scenarios: cancel / timeout / missing_binary
    # ------------------------------------------------------------------
    if case in ("cancel", "timeout", "missing_binary"):
        if case == "missing_binary" and not entry.subprocess:
            pytest.skip("missing_binary n/a for vanilla (no subprocess)")

        limits = (
            ResolvedLimits(max_iterations=2, max_tokens=100_000, timeout_seconds=0)
            if case == "timeout"
            else _LIMITS
        )

        if entry.subprocess:
            if case == "missing_binary":
                _patch_proc_missing_binary(monkeypatch)
            else:
                # cancel/timeout: spawn succeeds but the loop exits immediately
                proc = FakeProc([], returncode=0)
                patch_proc(monkeypatch, proc)  # type: ignore[arg-type]
            instance = entry.instance
        else:
            instance = type(entry.instance)(llm=ScriptedLLM([]))

        async def _run_new() -> None:
            cancel = asyncio.Event()
            if case == "cancel":
                cancel.set()  # pre-set → fires on first loop check
            await instance.run(  # type: ignore[union-attr]
                task=TaskBody(prompt="hi"),
                config=cfg,
                limits=limits,
                credential=CRED,
                emit=emit,
                cancel=cancel,
                workspace=ws,
            )

        asyncio.run(_run_new())
        return events, ws

    # ------------------------------------------------------------------
    # Original corpus-replay scenarios: success / error / multi_step
    # ------------------------------------------------------------------
    if entry.subprocess:
        corpus_file = _case_file(case)
        lines = (
            _CORPUS / entry.name / f"{corpus_file}.jsonl"
        ).read_text().splitlines(keepends=True)
        proc = FakeProc(lines, returncode=(1 if case == "error" else 0))
        patch_proc(monkeypatch, proc)  # type: ignore[arg-type]
        instance = entry.instance
    else:
        instance = type(entry.instance)(llm=ScriptedLLM(_vanilla_script(case)))

    async def _run() -> None:
        cancel = asyncio.Event()
        await instance.run(  # type: ignore[union-attr]
            task=TaskBody(prompt="hi"),
            config=cfg,
            limits=_LIMITS,
            credential=CRED,
            emit=emit,
            cancel=cancel,
            workspace=ws,
        )

    asyncio.run(_run())
    return events, ws

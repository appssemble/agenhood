"""Shared structured-output enforcement (structured output across all drivers).

One source of truth for extracting/validating a JSON value from agent text,
deciding native-flag eligibility, and phrasing the schema/retry prompts. Used
by the api, vanilla, codex, claude-code, and opencode drivers. Deliberately
imports nothing from the driver modules so any driver can import it.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import jsonschema

from agentcore.models import TaskResult

# 1 initial run + 2 correction retries (parity with the api driver's loop).
MAX_ATTEMPTS = 3

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n|\n?```$")

# Keywords the native strict modes (OpenAI strict structured outputs /
# Anthropic output_config) accept. Conservative whitelist: anything outside it
# fails native_subset_compatible and the schema is enforced by the backstop only.
_NATIVE_ALLOWED_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "description",
    "title",
    "anyOf",
    "format",  # accepted as annotation, not enforced
}


def validate_value(value: Any, schema: dict[str, Any]) -> str | None:
    """Validate ``value`` against ``schema``; return an error message or None."""
    try:
        jsonschema.validate(instance=value, schema=schema)
    except jsonschema.ValidationError as e:
        return f"output does not match the required schema: {e.message}"
    return None


def parse_and_validate(text: str, schema: dict[str, Any]) -> tuple[Any, str | None]:
    """Extract the first JSON value in ``text`` and validate it.

    Tolerates code fences and prose around the value; handles both object
    (``{...}``) and array (``[...]``) roots. Returns ``(parsed, None)`` on
    success or ``(None, error)`` on failure.
    """
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not starts:
        return None, "no JSON value found in the response"
    start = min(starts)
    end = cleaned.rfind("}" if cleaned[start] == "{" else "]")
    if end == -1:
        end = len(cleaned) - 1
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except ValueError as e:
        return None, f"invalid JSON: {e}"
    err = validate_value(parsed, schema)
    if err is not None:
        return None, err
    return parsed, None


def _node_ok(node: Any) -> bool:
    if isinstance(node, list):
        return all(_node_ok(n) for n in node)
    if not isinstance(node, dict):
        return True
    if any(key not in _NATIVE_ALLOWED_KEYS for key in node):
        return False
    if node.get("type") == "object":
        props = node.get("properties", {})
        if node.get("additionalProperties") is not False:
            return False
        if set(node.get("required", [])) != set(props):
            return False
        if not all(_node_ok(v) for v in props.values()):
            return False
    if "items" in node and not _node_ok(node["items"]):
        return False
    if "anyOf" in node and not _node_ok(node["anyOf"]):
        return False
    return True


def native_subset_compatible(schema: dict[str, Any]) -> bool:
    """True when ``schema`` fits the strict subset the native CLI flags accept.

    Requirements mirrored from OpenAI strict structured outputs / Anthropic
    output_config: object root; at every object level ``additionalProperties:
    false`` and every property required; no ``$ref``/``$defs``; whitelist of
    keywords only (``format`` tolerated as annotation). Conservative: anything
    unrecognized returns False — the schema is still fully enforced by the
    validation backstop, just without the native flag.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    return _node_ok(schema)


def schema_instructions(schema: dict[str, Any]) -> str:
    """The per-task prompt section telling a CLI agent the required output shape."""
    return (
        "## Output\n"
        "Your FINAL message must be ONLY a single JSON value matching this "
        "schema — no code fences, no prose before or after:\n"
        + json.dumps(schema)
    )


def correction_prompt(error: str) -> str:
    """The retry message fed to a resumed session after a failed validation."""
    return (
        f"Invalid output: {error}. Respond ONLY with a single JSON value "
        "matching the required schema — no code fences, no prose."
    )


async def run_structured_attempts(
    *,
    schema: dict[str, Any],
    task_prompt: str,
    timeout_seconds: int,
    emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    latest_id: dict[str, str | None],
    run_attempt: Callable[[str, str | None, int, bool], Awaitable[TaskResult]],
) -> TaskResult:
    """Drive a CLI driver's structured-output attempts (the spec's shared wrapper).

    ``run_attempt(prompt, resume_id, timeout_seconds, emit_running)`` performs
    one CLI invocation and returns its TaskResult WITHOUT emitting a terminal
    ``completed`` event (failure/cancel/timeout events are emitted inside the
    attempt as usual — the wrapper passes those results straight through).
    ``latest_id`` is the driver's mutable ``{"id": ...}`` session/thread
    holder, updated by the attempt as events stream; it is what makes a retry
    resume the session the previous attempt created.

    The attempt's candidate is ``result.output``: text is parsed then
    validated; an already-parsed object (claude's ``structured_output``) is
    validated directly. All attempts share one wall-clock deadline derived
    from ``timeout_seconds``.
    """
    prompt = f"{task_prompt}\n\n{schema_instructions(schema)}"
    deadline = time.monotonic() + timeout_seconds
    resume_id = latest_id["id"]
    attempt = 1
    while True:
        result = await run_attempt(
            prompt,
            resume_id,
            max(1, int(deadline - time.monotonic())),
            attempt == 1,
        )
        if not result.success:
            return result
        if isinstance(result.output, str):
            parsed, err = parse_and_validate(result.output, schema)
        else:
            parsed = result.output
            err = validate_value(parsed, schema)
            if err is not None:
                parsed = None
        if err is None:
            payload = {"success": True, "output": parsed}
            await emit(
                "status_change",
                {"from": "running", "to": "completed", "result": payload,
                 "error": None},
            )
            return TaskResult(success=True, output=parsed)
        if attempt >= MAX_ATTEMPTS or not latest_id["id"]:
            await emit(
                "status_change",
                {"from": "running", "to": "failed", "result": None,
                 "error": {"code": "invalid_structured_output", "message": err}},
            )
            return TaskResult(success=False, reason="invalid_structured_output")
        await emit(
            "log",
            {"level": "warn", "message": "structured_output_invalid",
             "data": {"attempt": attempt, "max_attempts": MAX_ATTEMPTS,
                      "error": err}},
        )
        resume_id = latest_id["id"]
        prompt = correction_prompt(err)
        attempt += 1

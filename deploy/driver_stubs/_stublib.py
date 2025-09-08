#!/usr/bin/env python3
"""Shared helpers for the CLI driver stubs (stdlib only)."""
from __future__ import annotations

import json
import os
import sys
import time

SCRIPT_MARKER = "@@SCRIPT@@"


def parse_directive(text: str) -> dict:
    if not isinstance(text, str) or SCRIPT_MARKER not in text:
        return {}
    raw = text.split(SCRIPT_MARKER, 1)[1].strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def read_script(source: str) -> dict:
    if source == "argv":
        text = sys.argv[-1] if len(sys.argv) > 1 else ""
    else:
        text = sys.stdin.read()
    return parse_directive(text)


def materialize_files(script: dict, cwd: str) -> None:
    for turn in script.get("turns", []):
        if turn.get("tool") == "write_file":
            inp = turn.get("input", {})
            path = inp.get("path")
            if not path:
                continue
            target = os.path.join(cwd, path)
            os.makedirs(os.path.dirname(target) or cwd, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(inp.get("content", ""))


def final_text(script: dict) -> str:
    last = ""
    for turn in script.get("turns", []):
        if isinstance(turn.get("text"), str):
            last = turn["text"]
        if "done" in turn:
            out = turn["done"].get("output", "")
            last = out if isinstance(out, str) else json.dumps(out)
    return last


def maybe_sleep(script: dict) -> None:
    ms = int(script.get("delay_ms") or 0)
    if ms:
        time.sleep(ms / 1000.0)


def is_error(script: dict) -> bool:
    if script.get("http_error"):
        return True
    for turn in script.get("turns", []):
        if "done" in turn and turn["done"].get("success") is False:
            return True
    return False


def is_malformed(script: dict) -> bool:
    return bool(script.get("malformed"))


def is_never_done(script: dict) -> bool:
    return bool(script.get("never_done"))


def usage(script: dict) -> tuple[int, int]:
    u = script.get("usage") or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def error_message(script: dict) -> str:
    for turn in script.get("turns", []):
        if "done" in turn and turn["done"].get("success") is False:
            return turn["done"].get("reason", "model reported failure")
    return "stubbed error"


def hang_forever() -> None:
    while True:
        time.sleep(3600)

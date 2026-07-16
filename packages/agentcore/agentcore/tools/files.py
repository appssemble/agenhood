from __future__ import annotations

import os
import time
from typing import Any

from agentcore import sandbox
from agentcore.tools.base import ToolContext, ToolResult, ToolSpec, _ms, register
from agentcore.tools.paths import RESERVED_DIRS, PathError, safe_resolve

MAX_READ_BYTES = 1024 * 1024  # 1 MiB
LIST_MAX_FILES = 2000


def _ok(content: str, start: float) -> ToolResult:
    return ToolResult(ok=True, content=content, duration_ms=_ms(start))


def _err(content: str, start: float) -> ToolResult:
    return ToolResult(ok=False, content=content, duration_ms=_ms(start))


class ReadFileTool:
    spec = ToolSpec(
        name="read_file",
        description="Read a UTF-8 text file from /workspace. Returns up to 1 MiB.",
        input_schema={
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            target = safe_resolve(ctx.workspace, input["path"], allow_skills_read=True)
        except PathError as e:
            return _err(str(e), start)
        if not os.path.isfile(target):
            return _err(f"file not found: {input['path']}", start)
        with open(target, "rb") as f:
            data = f.read(MAX_READ_BYTES + 1)
        truncated = len(data) > MAX_READ_BYTES
        text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += "\n[...truncated at 1 MiB...]"
        return _ok(text, start)


class WriteFileTool:
    spec = ToolSpec(
        name="write_file",
        description="Write/overwrite a file under /workspace. Creates parent dirs.",
        input_schema={
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            target = safe_resolve(ctx.workspace, input["path"])
        except PathError as e:
            return _err(str(e), start)
        sandbox.makedirs_agent(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as f:
            f.write(input["content"])
        sandbox.chown_to_agent(target)
        return _ok(f"wrote {len(input['content'])} bytes to {input['path']}", start)


class EditFileTool:
    spec = ToolSpec(
        name="edit_file",
        description=(
            "Replace old_string with new_string in a file. "
            "old_string must appear exactly once."
        ),
        input_schema={
            "type": "object",
            "required": ["path", "old_string", "new_string"],
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            target = safe_resolve(ctx.workspace, input["path"])
        except PathError as e:
            return _err(str(e), start)
        if not os.path.isfile(target):
            return _err(f"file not found: {input['path']}", start)
        with open(target, encoding="utf-8") as f:
            text = f.read()
        count = text.count(input["old_string"])
        if count == 0:
            return _err("old_string not found in file", start)
        if count > 1:
            return _err(
                f"old_string matched {count} times; it must match exactly once",
                start,
            )
        new_text = text.replace(input["old_string"], input["new_string"], 1)
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_text)
        sandbox.chown_to_agent(target)
        return _ok(f"edited {input['path']}", start)


class ListFilesTool:
    spec = ToolSpec(
        name="list_files",
        description=(
            "List files under a path in /workspace"
            " (excludes .agent-runtime/ and .agent-state/)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_root = input.get("path", "")
        try:
            if rel_root:
                root = safe_resolve(
                    ctx.workspace, rel_root, allow_skills_read=True
                )
            else:
                root = os.path.realpath(ctx.workspace)
        except PathError as e:
            return _err(str(e), start)
        max_depth = int(input.get("max_depth", 10))
        ws = os.path.realpath(ctx.workspace)
        lines: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in RESERVED_DIRS]
            depth = dirpath[len(ws):].count(os.sep)
            if depth >= max_depth:
                dirnames[:] = []
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ws)
                size = os.path.getsize(full)
                lines.append(f"{rel}\t{size}")
                if len(lines) >= LIST_MAX_FILES:
                    lines.append("[...truncated...]")
                    return _ok("\n".join(lines), start)
        return _ok("\n".join(lines) if lines else "(empty)", start)


class DeleteFileTool:
    spec = ToolSpec(
        name="delete_file",
        description="Delete a single file under /workspace. Refuses directories.",
        input_schema={
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        try:
            target = safe_resolve(ctx.workspace, input["path"])
        except PathError as e:
            return _err(str(e), start)
        if os.path.isdir(target):
            return _err("path is a directory; use bash to remove directories", start)
        if not os.path.isfile(target):
            return _err(f"file not found: {input['path']}", start)
        os.remove(target)
        return _ok(f"deleted {input['path']}", start)


register(ReadFileTool())
register(WriteFileTool())
register(EditFileTool())
register(ListFilesTool())
register(DeleteFileTool())

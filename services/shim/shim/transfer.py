"""Workspace export/import helpers for workflow step file transfer.

Backs the shim's ``GET /files/export`` and ``POST /files/import`` routes:
glob expansion against the workspace, a bounded-memory uncompressed-tar
stream writer, and a guarded tar extractor. Reserved dirs and .git never
cross the wire, at any depth; symlinks are never followed or created.
"""
from __future__ import annotations

import os
import re
import tarfile
from collections.abc import Iterator
from typing import Any

from agentcore import sandbox
from agentcore.tools.paths import RESERVED_DIRS

_EXCLUDED_NAMES = (*RESERVED_DIRS, ".git")
_CHUNK = 64 * 1024
_TAR_BLOCK = 512


class TarImportError(ValueError):
    """A tar member violates the workspace import guards."""


def _pattern_regex(pat: str) -> re.Pattern[str]:
    """Translate an export glob to a full-relative-path regex.

    ``*`` and ``?`` never cross ``/``; a segment that is exactly ``**``
    matches any number of segments (including none). Mirrors
    ``glob.glob(recursive=True)`` for the supported pattern forms, but is
    applied to an os.walk listing so symlinked directories are never
    traversed.
    """
    segs = pat.split("/")
    regex = ""
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == "**":
            regex += ".*" if last else "(?:[^/]+/)*"
            continue
        for ch in seg:
            if ch == "*":
                regex += "[^/]*"
            elif ch == "?":
                regex += "[^/]"
            else:
                regex += re.escape(ch)
        if not last:
            regex += "/"
    return re.compile("^" + regex + "$")


def expand_exports(
    workspace: str, patterns: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Expand export patterns against the workspace.

    Returns ``(files, unmatched)``: ``files`` is a sorted, de-duplicated list
    of ``{"path", "size"}`` for every REGULAR file matched by at least one
    pattern; ``unmatched`` lists patterns that matched no regular file.
    The workspace is walked with ``followlinks=False`` and symlinks are
    skipped outright, so symlinked directories are never traversed.
    Directory matches don't count — export ``dir/**`` to ship a directory.
    """
    ws = os.path.realpath(workspace)
    all_files: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(ws, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_NAMES]
        for name in filenames:
            if name in _EXCLUDED_NAMES:
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:  # vanished mid-walk — best-effort, like the zip
                continue
            all_files.append((os.path.relpath(full, ws), size))
    seen: dict[str, int] = {}
    unmatched: list[str] = []
    for pat in patterns:
        rx = _pattern_regex(pat)
        hits = [(rel, size) for rel, size in all_files if rx.match(rel)]
        if not hits:
            unmatched.append(pat)
        for rel, size in hits:
            seen[rel] = size
    files = [{"path": p, "size": s} for p, s in sorted(seen.items())]
    return files, unmatched


def stream_export_tar(
    workspace: str, files: list[dict[str, Any]]
) -> Iterator[bytes]:
    """Yield an uncompressed tar of ``files`` in bounded memory.

    Headers come from ``TarInfo.tobuf`` and file bytes stream in 64 KiB
    chunks. A file that shrinks mid-stream is zero-padded to its declared
    size and one that grows is truncated, so the archive always matches its
    headers.
    """
    ws = os.path.realpath(workspace)
    for f in files:
        full = os.path.join(ws, f["path"])
        info = tarfile.TarInfo(name=f["path"])
        info.size = int(f["size"])
        info.mode = 0o644
        info.mtime = int(os.path.getmtime(full))
        yield info.tobuf(tarfile.PAX_FORMAT)
        remaining = info.size
        with open(full, "rb") as src:
            while remaining > 0:
                chunk = src.read(min(_CHUNK, remaining))
                if not chunk:
                    yield b"\0" * remaining
                    remaining = 0
                    break
                yield chunk
                remaining -= len(chunk)
        pad = (-info.size) % _TAR_BLOCK
        if pad:
            yield b"\0" * pad
    yield b"\0" * (2 * _TAR_BLOCK)


def _member_target(workspace: str, name: str) -> str:
    """Validate a member path; return its absolute target under workspace."""
    if not name or name.startswith(("/", "\\")):
        raise TarImportError(f"absolute path not allowed: {name!r}")
    parts = name.replace("\\", "/").split("/")
    if ".." in parts:
        raise TarImportError(f"path traversal not allowed: {name!r}")
    if any(p in _EXCLUDED_NAMES for p in parts):
        raise TarImportError(f"reserved path not allowed: {name!r}")
    ws = os.path.realpath(workspace)
    target = os.path.realpath(os.path.join(ws, name))
    if target != ws and not target.startswith(ws + os.sep):
        raise TarImportError(f"path escape not allowed: {name!r}")
    return target


def extract_import_tar(workspace: str, archive_path: str) -> dict[str, int]:
    """Unpack a spooled tar under the workspace with strict guards.

    Regular files and directories only — symlink/hardlink/device members
    raise TarImportError, as does any absolute, traversing, or reserved
    path. Existing files are overwritten. Returns counters for the caller.
    """
    files_written = 0
    bytes_written = 0
    with tarfile.open(archive_path, mode="r") as tf:
        for member in tf:
            target = _member_target(workspace, member.name)
            if member.isdir():
                sandbox.makedirs_agent(target)
                continue
            if not member.isreg():
                raise TarImportError(f"unsupported member type: {member.name!r}")
            sandbox.makedirs_agent(os.path.dirname(target))
            src = tf.extractfile(member)
            if src is None:
                raise TarImportError(f"unreadable member: {member.name!r}")
            with open(target, "wb") as dst:
                while True:
                    chunk = src.read(_CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
                    bytes_written += len(chunk)
            sandbox.chown_to_agent(target)
            files_written += 1
    return {"files_written": files_written, "bytes_written": bytes_written}

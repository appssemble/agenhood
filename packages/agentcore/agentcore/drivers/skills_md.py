# packages/agentcore/agentcore/drivers/skills_md.py
"""Pure helpers for opencode Agent Skills: SKILL.md rendering + name validation.

opencode requires the skill folder name to equal the frontmatter ``name`` and
to match ``^[a-z0-9]+(-[a-z0-9]+)*$`` (1-64 chars); ``description`` is 1-1024
chars. We render frontmatter ourselves so it is always well-formed — no YAML
dependency: ``description`` is emitted as an escaped double-quoted scalar with
newlines collapsed to spaces (it is single-line by contract).
"""

from __future__ import annotations

import base64
import gzip
import io
import re
import shutil
import tarfile
from pathlib import Path

from agentcore.models import ShimSkill

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def extract_bundle(
    dest_dir: Path, bundle_b64: str, *, max_files: int, max_bytes: int
) -> None:
    """Safely unpack a base64 gzip-tar skill bundle into ``dest_dir``.

    Hardened against hostile archives: only regular files and directories are
    written; symlinks/hardlinks/devices, absolute paths, and ``..`` escapes are
    rejected (ValueError); cumulative uncompressed size and file count are
    capped. ``dest_dir`` is created if missing. On any rejection the caller is
    expected to discard ``dest_dir`` (write_skills owns the managed tree)."""
    raw = gzip.decompress(base64.b64decode(bundle_b64))
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = dest_dir.resolve()
    total = 0
    count = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsafe member type in bundle: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe member type in bundle: {member.name}")
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"unsafe path in bundle: {name}")
            target = (base / name).resolve()
            if base != target and base not in target.parents:
                raise ValueError(f"path escapes bundle dir: {name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            count += 1
            total += member.size
            if count > max_files:
                raise ValueError(f"bundle exceeds {max_files} files")
            if total > max_bytes:
                raise ValueError(f"bundle exceeds {max_bytes} bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            target.write_bytes(src.read() if src else b"")


MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_FILES = 200


def valid_skill_name(name: str) -> bool:
    return 1 <= len(name) <= MAX_NAME and bool(SKILL_NAME_RE.match(name))


def _yaml_dq(value: str) -> str:
    """Escape a string as a YAML double-quoted scalar (newlines → spaces)."""
    collapsed = " ".join(value.splitlines())
    escaped = collapsed.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_skill_md(*, name: str, description: str, body: str) -> str:
    """Assemble a SKILL.md document from structured fields."""
    front = f"---\nname: {name}\ndescription: {_yaml_dq(description)}\n---\n"
    return f"{front}\n{body}" if body else front


async def write_skills(skills_dir: str, skills: list[ShimSkill]) -> list[str]:
    """Materialize skills as ``<skills_dir>/<name>/SKILL.md`` and return the
    names written. Path-agnostic so every driver can reuse it with its own
    discovery dir. The managed dir is cleared first so a deselected skill from a
    prior run never lingers; invalid names are skipped (never written, no path
    escape). The caller owns ``skills_dir`` entirely (a hidden runtime dir)."""
    base = Path(skills_dir)
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    written: list[str] = []
    for skill in skills:
        if not valid_skill_name(skill.name):
            continue
        folder = base / skill.name
        if skill.bundle_b64:
            try:
                extract_bundle(
                    folder, skill.bundle_b64,
                    max_files=MAX_BUNDLE_FILES, max_bytes=MAX_BUNDLE_BYTES,
                )
            except Exception:  # noqa: BLE001 — a bad bundle must not abort the batch
                shutil.rmtree(folder, ignore_errors=True)
                continue
            if not (folder / "SKILL.md").exists():
                shutil.rmtree(folder, ignore_errors=True)
                continue
        else:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(
                render_skill_md(
                    name=skill.name, description=skill.description, body=skill.body
                )
            )
        written.append(skill.name)
    return written

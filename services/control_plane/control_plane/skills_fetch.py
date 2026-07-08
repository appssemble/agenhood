# services/control_plane/control_plane/skills_fetch.py
"""Fetch, pin, validate, and pack a third-party skill from a git repo.

The control plane (which has direct internet via the ``default`` network) clones
the skill subpath at an immutable commit SHA, reads its SKILL.md, enforces size
caps, and returns a gzip-tar bundle for caching. Content is read/packed only —
never executed."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from agentcore.drivers.skills_md import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    MAX_DESCRIPTION,
    valid_skill_name,
)
from agentcore.git_ssh import build_ssh_command, classify_remote_error
from control_plane.git_remotes_service import remote_host, validate_remote_url

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_TIMEOUT = 60  # seconds per git invocation


def parse_skill_frontmatter(md: str) -> tuple[str, str, str]:
    """Return (name, description, body) from a SKILL.md string.

    Minimal frontmatter parser (no YAML dep): the document must open with a
    ``---`` line, contain ``name:`` and ``description:`` keys before the closing
    ``---``, and the remainder is the body. Quotes around the description are
    stripped. Raises ValueError if frontmatter or required keys are missing."""
    if not md.startswith("---"):
        raise ValueError("SKILL.md missing frontmatter")
    parts = md.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter not closed")
    front, body = parts[1], parts[2]
    fields: dict[str, str] = {}
    for line in front.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            fields[key.strip()] = val.strip().strip('"').strip()
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name:
        raise ValueError("SKILL.md frontmatter missing name")
    if not description:
        raise ValueError("SKILL.md frontmatter missing description")
    return name, description, body.lstrip("\n")


def pack_dir(
    root: Path, *, max_files: int, max_bytes: int
) -> tuple[bytes, int, str]:
    """Pack ``root`` into a deterministic gzip-tar (members relative to root,
    sorted). Only regular files and directories are included — symlinks and
    special files are skipped. Enforces file-count and uncompressed-byte caps.
    Returns (gzip_bytes, uncompressed_size, sha256_hex_of_gzip_bytes)."""
    entries = sorted(
        p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
    )
    if len(entries) > max_files:
        raise ValueError(f"skill exceeds {max_files} files")
    total = 0
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for p in entries:
            size = p.stat().st_size
            total += size
            if total > max_bytes:
                raise ValueError(f"skill exceeds {max_bytes} bytes")
            info = tarfile.TarInfo(str(p.relative_to(root).as_posix()))
            info.size = size
            info.mode = 0o644
            info.mtime = 0
            with p.open("rb") as fh:
                tar.addfile(info, fh)
    gz = gzip.compress(raw.getvalue(), mtime=0)
    return gz, total, hashlib.sha256(gz).hexdigest()


@dataclass(frozen=True)
class FetchedSkill:
    name: str
    description: str
    body: str
    pinned_sha: str
    bundle: bytes
    bundle_sha256: str
    bundle_size: int


def _run_git(args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=_GIT_TIMEOUT, env={**os.environ, **env} if env else None,
    )
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _validate_url(url: str, *, has_key: bool = False) -> None:
    if has_key:
        try:
            validate_remote_url(url)  # ssh-only; rejects http(s), bad hosts
        except ValueError as exc:
            raise ValueError(f"with a deploy key, source_url must be an ssh URL: {exc}") from exc
        return
    if url.startswith("https://"):
        return
    if url.startswith("file://") and os.environ.get("AGENHOOD_ALLOW_FILE_SKILL_SOURCE") == "1":
        return
    if url.startswith("file://"):
        raise ValueError(
            "file:// skill sources are disabled in production; "
            "set AGENHOOD_ALLOW_FILE_SKILL_SOURCE=1 to enable in tests"
        )
    raise ValueError("source_url must be an https:// git URL")


_KNOWN_HOSTS = os.path.join(tempfile.gettempdir(), "agenhood-skills-known-hosts")


@contextmanager
def _git_env(url: str, private_key: str | None):
    """Yield the env dict for git subprocesses: None for anonymous https, a
    GIT_SSH_COMMAND pointing at an ephemeral 0600 key file for ssh. The key
    file lives only for the duration of this context manager."""
    if private_key is None:
        yield None
        return
    with tempfile.TemporaryDirectory() as d:
        key_path = os.path.join(d, "key")
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key if private_key.endswith("\n") else private_key + "\n")
        yield {
            "GIT_SSH_COMMAND": build_ssh_command(
                key_path=key_path, known_hosts=_KNOWN_HOSTS, host=remote_host(url),
            )
        }


def _remote_error(exc: ValueError) -> ValueError:
    """Prefix a git remote failure with its stable classify_remote_error code."""
    return ValueError(f"{classify_remote_error(str(exc))}: {exc}")


def list_branches(
    url: str, *, private_key: str | None = None
) -> tuple[list[str], str | None]:
    """List a remote's branch names and its default branch.

    A single ``ls-remote --symref`` advertises every ref plus the symbolic
    target of HEAD, so we derive both from one round-trip. Tags are ignored.
    The default branch (when known) is sorted first so the UI can preselect it.
    Raises ValueError on a rejected URL (bad scheme) or an unreachable remote;
    the caller maps those to 422/502 respectively. When ``private_key`` is
    given, ``url`` must be an ssh URL and remote failures are prefixed with a
    stable error code (e.g. ``auth_failed: ...``)."""
    _validate_url(url, has_key=private_key is not None)
    with _git_env(url, private_key) as env:
        try:
            out = _run_git(["ls-remote", "--symref", url], env=env)
        except ValueError as exc:
            raise _remote_error(exc) from exc
    default: str | None = None
    branches: list[str] = []
    for line in out.splitlines():
        if line.startswith("ref: "):
            target, _, name = line[len("ref: "):].partition("\t")
            if name.strip() == "HEAD" and target.startswith("refs/heads/"):
                default = target[len("refs/heads/"):]
            continue
        _sha, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])
    branches = sorted(set(branches))
    if default and default in branches:
        branches = [default, *(b for b in branches if b != default)]
    return branches, default


def resolve_sha(url: str, ref: str, *, env: dict[str, str] | None = None) -> str:
    """Resolve ``ref`` (tag/branch/SHA) to an immutable commit SHA. Runs inside
    the caller's ``_git_env`` context, which is why ``env`` is passed in rather
    than derived here."""
    if _SHA_RE.match(ref):
        return ref
    try:
        out = _run_git(["ls-remote", url, "--", ref], env=env)
    except ValueError as exc:
        raise _remote_error(exc) from exc
    if not out:
        raise ValueError(f"ref {ref!r} not found in {url}")
    return out.split()[0]


def fetch_git_skill(
    *, url: str, subpath: str, ref: str,
    max_files: int = MAX_BUNDLE_FILES, max_bytes: int = MAX_BUNDLE_BYTES,
    private_key: str | None = None,
) -> FetchedSkill:
    """Clone the skill subpath at the pinned SHA, validate its SKILL.md, and
    pack it. ``subpath`` is the directory containing SKILL.md ('' = repo root).
    Raises ValueError on any validation/fetch failure (the caller maps to 422).
    When ``private_key`` is given, ``url`` must be an ssh URL and the clone
    runs with a GIT_SSH_COMMAND pointed at an ephemeral 0600 key file that is
    gone by the time this function returns."""
    _validate_url(url, has_key=private_key is not None)
    sub = subpath.strip().strip("/")
    if ".." in Path(sub).parts:
        raise ValueError("source_subpath must not contain '..'")
    with _git_env(url, private_key) as env:
        sha = resolve_sha(url, ref, env=env)
        with tempfile.TemporaryDirectory() as tmp:
            _run_git(["init", "-q", tmp])
            _run_git(["-C", tmp, "remote", "add", "origin", url])
            try:
                _run_git(["-C", tmp, "fetch", "-q", "--depth", "1", "origin", sha], env=env)
            except ValueError as exc:
                raise _remote_error(exc) from exc
            _run_git(["-C", tmp, "checkout", "-q", sha])
            skill_root = Path(tmp) / sub if sub else Path(tmp)
            skill_md = skill_root / "SKILL.md"
            if not skill_md.is_file():
                # Zero-friction fallback: find where the skill actually lives.
                # With no explicit subpath and exactly one SKILL.md in the repo,
                # descend into it; otherwise name the candidates in the error.
                candidates = sorted(
                    p.parent.relative_to(tmp).as_posix()
                    for p in Path(tmp).glob("**/SKILL.md")
                    if ".git" not in p.parts
                )[:10]
                if not sub and len(candidates) == 1:
                    sub = candidates[0]
                    skill_root = Path(tmp) / sub
                    skill_md = skill_root / "SKILL.md"
                elif candidates:
                    raise ValueError(
                        f"no SKILL.md at subpath {subpath!r} — found SKILL.md in: "
                        + ", ".join(candidates)
                        + ". Set the subpath to one of these."
                    )
                else:
                    raise ValueError(
                        f"no SKILL.md at subpath {subpath!r} (no SKILL.md anywhere "
                        "in the repository at this ref)"
                    )
            name, description, body = parse_skill_frontmatter(skill_md.read_text())
            if not valid_skill_name(name):
                raise ValueError(
                    f"SKILL.md name {name!r} must match ^[a-z0-9]+(-[a-z0-9]+)*$ "
                    "and be 1-64 chars"
                )
            if len(description) > MAX_DESCRIPTION:
                raise ValueError(
                    f"SKILL.md description exceeds {MAX_DESCRIPTION} chars"
                )
            bundle, size, sha256 = pack_dir(
                skill_root, max_files=max_files, max_bytes=max_bytes
            )
    return FetchedSkill(
        name=name, description=description, body=body, pinned_sha=sha,
        bundle=bundle, bundle_sha256=sha256, bundle_size=size,
    )

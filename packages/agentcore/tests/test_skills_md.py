# packages/agentcore/tests/test_skills_md.py
from __future__ import annotations

import base64
import gzip
import io
import tarfile
from pathlib import Path

import pytest

from agentcore.drivers.skills_md import (
    SKILL_NAME_RE,
    render_skill_md,
    valid_skill_name,
    write_skills,
)
from agentcore.models import ShimSkill

pytestmark = pytest.mark.unit


def test_valid_skill_name() -> None:
    assert valid_skill_name("git-release")
    assert valid_skill_name("a")
    assert valid_skill_name("a1-b2-c3")
    assert not valid_skill_name("Git-Release")     # uppercase
    assert not valid_skill_name("-lead")           # leading hyphen
    assert not valid_skill_name("trail-")          # trailing hyphen
    assert not valid_skill_name("dbl--hyphen")     # double hyphen
    assert not valid_skill_name("has space")
    assert not valid_skill_name("")
    assert not valid_skill_name("x" * 65)          # too long


def test_render_skill_md_basic() -> None:
    md = render_skill_md(name="git-release", description="Make releases", body="# Do it\nstep")
    assert md.startswith("---\n")
    assert "name: git-release\n" in md
    assert 'description: "Make releases"\n' in md
    assert md.rstrip().endswith("step")
    # frontmatter closes before the body
    assert md.index("---", 4) < md.index("# Do it")


def test_render_skill_md_escapes_description() -> None:
    # A description with quotes, backslashes, and a colon must not corrupt YAML.
    md = render_skill_md(
        name="x", description='He said "hi": a\\b', body="",
    )
    assert 'description: "He said \\"hi\\": a\\\\b"\n' in md


def test_render_skill_md_strips_newlines_in_description() -> None:
    md = render_skill_md(name="x", description="line1\nline2\r\nline3", body="")
    # newlines collapsed to spaces so the frontmatter stays single-line
    assert "description: \"line1 line2 line3\"\n" in md
    assert "line1\nline2" not in md.split("---", 2)[1]


def test_name_regex_is_exported() -> None:
    assert SKILL_NAME_RE.match("ok-name")
    assert not SKILL_NAME_RE.match("Bad")


async def test_write_skills_writes_skill_md_per_valid_skill(tmp_path):
    base = str(tmp_path / "skills")
    written = await write_skills(base, [
        ShimSkill(name="git-release", description="Make releases", body="# Steps\n1"),
        ShimSkill(name="lint", description="Run linters", body=""),
    ])
    assert sorted(written) == ["git-release", "lint"]
    md = (Path(base) / "git-release" / "SKILL.md").read_text()
    assert "name: git-release" in md
    assert 'description: "Make releases"' in md
    assert "# Steps" in md
    assert (Path(base) / "lint" / "SKILL.md").exists()


async def test_write_skills_clears_stale(tmp_path):
    base = Path(tmp_path / "skills")
    (base / "old").mkdir(parents=True)
    (base / "old" / "SKILL.md").write_text("stale")
    await write_skills(str(base), [ShimSkill(name="new", description="d", body="")])
    assert not (base / "old").exists()
    assert (base / "new" / "SKILL.md").exists()


async def test_write_skills_empty_is_noop(tmp_path):
    assert await write_skills(str(tmp_path / "skills"), []) == []


async def test_write_skills_skips_invalid_names_no_escape(tmp_path):
    base = tmp_path / "skills"
    written = await write_skills(str(base), [ShimSkill(name="../escape", description="d", body="")])
    assert written == []
    assert list(Path(tmp_path).rglob("SKILL.md")) == []


def _make_bundle(files: dict[str, bytes]) -> str:
    """Build a base64 gzip-tar from {relative_path: content}."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return base64.b64encode(gzip.compress(raw.getvalue())).decode()


def test_extract_bundle_writes_tree(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    b64 = _make_bundle({
        "SKILL.md": b"---\nname: x\ndescription: \"d\"\n---\nhi",
        "scripts/run.sh": b"echo hi\n",
    })
    extract_bundle(tmp_path, b64, max_files=200, max_bytes=5_000_000)
    assert (tmp_path / "SKILL.md").read_text().startswith("---")
    assert (tmp_path / "scripts" / "run.sh").read_text() == "echo hi\n"


def test_extract_bundle_rejects_path_traversal(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    b64 = _make_bundle({"../escape.txt": b"nope"})
    with pytest.raises(ValueError):
        extract_bundle(tmp_path, b64, max_files=200, max_bytes=5_000_000)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_extract_bundle_rejects_absolute_path(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    b64 = _make_bundle({"/etc/evil": b"nope"})
    with pytest.raises(ValueError):
        extract_bundle(tmp_path, b64, max_files=200, max_bytes=5_000_000)


def test_extract_bundle_rejects_symlink(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    b64 = base64.b64encode(gzip.compress(raw.getvalue())).decode()
    with pytest.raises(ValueError):
        extract_bundle(tmp_path, b64, max_files=200, max_bytes=5_000_000)


def test_extract_bundle_enforces_byte_cap(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    b64 = _make_bundle({"SKILL.md": b"x" * 1000})
    with pytest.raises(ValueError):
        extract_bundle(tmp_path, b64, max_files=200, max_bytes=500)


def test_extract_bundle_enforces_file_cap(tmp_path) -> None:
    from agentcore.drivers.skills_md import extract_bundle
    b64 = _make_bundle({f"f{i}.txt": b"a" for i in range(5)})
    with pytest.raises(ValueError):
        extract_bundle(tmp_path, b64, max_files=3, max_bytes=5_000_000)


async def test_write_skills_materializes_bundle(tmp_path) -> None:
    from agentcore.drivers.skills_md import write_skills
    from agentcore.models import ShimSkill
    b64 = _make_bundle({
        "SKILL.md": b"---\nname: pdf\ndescription: \"d\"\n---\nbody",
        "ref/notes.md": b"notes",
    })
    names = await write_skills(str(tmp_path), [
        ShimSkill(name="pdf", description="d", bundle_b64=b64),
    ])
    assert names == ["pdf"]
    assert (tmp_path / "pdf" / "SKILL.md").exists()
    assert (tmp_path / "pdf" / "ref" / "notes.md").read_text() == "notes"


async def test_write_skills_inline_still_renders(tmp_path) -> None:
    from agentcore.drivers.skills_md import write_skills
    from agentcore.models import ShimSkill
    names = await write_skills(str(tmp_path), [
        ShimSkill(name="inline", description="d", body="hello"),
    ])
    assert names == ["inline"]
    assert "hello" in (tmp_path / "inline" / "SKILL.md").read_text()


async def test_write_skills_bad_bundle_is_skipped(tmp_path) -> None:
    # A bundle that fails extraction must not crash the batch nor leave the name.
    from agentcore.drivers.skills_md import write_skills
    from agentcore.models import ShimSkill
    names = await write_skills(str(tmp_path), [
        ShimSkill(name="bad", description="d", bundle_b64="not-valid-base64-gzip"),
        ShimSkill(name="ok", description="d", body="hi"),
    ])
    assert names == ["ok"]
    assert not (tmp_path / "bad").exists()

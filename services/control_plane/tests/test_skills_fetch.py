import gzip
import io
import subprocess
import tarfile

import pytest

from control_plane.skills_fetch import (
    FetchedSkill,
    fetch_git_skill,
    list_branches,
    pack_dir,
    parse_skill_frontmatter,
)

pytestmark = pytest.mark.unit


# Enable file:// git sources for all tests in this module (Fix 4: production
# disallows file:// — tests opt-in with AGENHOOD_ALLOW_FILE_SKILL_SOURCE=1).
@pytest.fixture(autouse=True)
def _allow_file_sources(monkeypatch):
    monkeypatch.setenv("AGENHOOD_ALLOW_FILE_SKILL_SOURCE", "1")


# ---------------------------------------------------------------------------
# Task C1: parse_skill_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_basic() -> None:
    md = '---\nname: pdf-tools\ndescription: "Edit PDFs"\n---\n# Body\nstep'
    name, desc, body = parse_skill_frontmatter(md)
    assert name == "pdf-tools"
    assert desc == "Edit PDFs"
    assert body.strip() == "# Body\nstep"


def test_parse_frontmatter_unquoted_description() -> None:
    md = "---\nname: x\ndescription: plain text\n---\nbody"
    name, desc, _ = parse_skill_frontmatter(md)
    assert name == "x"
    assert desc == "plain text"


def test_parse_frontmatter_missing_frontmatter() -> None:
    with pytest.raises(ValueError):
        parse_skill_frontmatter("no frontmatter here")


def test_parse_frontmatter_missing_name() -> None:
    with pytest.raises(ValueError):
        parse_skill_frontmatter('---\ndescription: "d"\n---\nbody')


def test_parse_frontmatter_missing_description() -> None:
    with pytest.raises(ValueError):
        parse_skill_frontmatter("---\nname: x\n---\nbody")


# ---------------------------------------------------------------------------
# Task C2: pack_dir
# ---------------------------------------------------------------------------


def test_pack_dir_roundtrips(tmp_path) -> None:
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\nb")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text("echo hi")
    data, size, sha = pack_dir(tmp_path, max_files=200, max_bytes=5_000_000)
    members = set()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data)), mode="r") as tar:
        members = {m.name for m in tar.getmembers() if m.isfile()}
    assert "SKILL.md" in members
    assert "scripts/run.sh" in members
    assert size > 0
    assert len(sha) == 64


def test_pack_dir_enforces_byte_cap(tmp_path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 2000)
    with pytest.raises(ValueError):
        pack_dir(tmp_path, max_files=200, max_bytes=500)


def test_pack_dir_enforces_file_cap(tmp_path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("a")
    with pytest.raises(ValueError):
        pack_dir(tmp_path, max_files=3, max_bytes=5_000_000)


def test_pack_dir_skips_symlinks(tmp_path) -> None:
    (tmp_path / "SKILL.md").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "SKILL.md")
    data, _, _ = pack_dir(tmp_path, max_files=200, max_bytes=5_000_000)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data)), mode="r") as tar:
        assert all(not m.issym() for m in tar.getmembers())


# ---------------------------------------------------------------------------
# Task C3: fetch_git_skill / resolve_sha
# ---------------------------------------------------------------------------


def _git(args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def _make_repo(tmp_path):
    """Create a local git repo with skills/pdf/SKILL.md; return (url, sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    skill_dir = repo / "skills" / "pdf"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: pdf\ndescription: "Edit PDFs"\n---\n# Use it\n'
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.sh").write_text("echo hi\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"file://{repo}", sha


@pytest.mark.unit
def test_fetch_git_skill_by_ref(tmp_path) -> None:
    url, sha = _make_repo(tmp_path)
    out = fetch_git_skill(url=url, subpath="skills/pdf", ref="main")
    assert isinstance(out, FetchedSkill)
    assert out.name == "pdf"
    assert out.description == "Edit PDFs"
    assert out.pinned_sha == sha
    assert out.bundle_size > 0
    assert len(out.bundle_sha256) == 64
    assert out.bundle  # non-empty bytes


@pytest.mark.unit
def test_fetch_git_skill_pins_by_sha(tmp_path) -> None:
    url, sha = _make_repo(tmp_path)
    out = fetch_git_skill(url=url, subpath="skills/pdf", ref=sha)
    assert out.pinned_sha == sha


@pytest.mark.unit
def test_fetch_git_skill_missing_skill_md(tmp_path) -> None:
    url, _ = _make_repo(tmp_path)
    with pytest.raises(ValueError):
        fetch_git_skill(url=url, subpath="skills/nope", ref="main")


@pytest.mark.unit
def test_fetch_blank_subpath_auto_descends_to_single_skill(tmp_path) -> None:
    """No subpath + exactly one SKILL.md in the repo → find and use it."""
    url, sha = _make_repo(tmp_path)
    out = fetch_git_skill(url=url, subpath="", ref="main")
    assert out.name == "pdf"
    assert out.pinned_sha == sha


@pytest.mark.unit
def test_fetch_blank_subpath_multiple_skills_names_candidates(tmp_path) -> None:
    repo = tmp_path / "multi"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    for name in ("alpha", "beta"):
        d = repo / name
        d.mkdir()
        (d / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "d"\n---\nbody\n')
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    with pytest.raises(ValueError, match=r"alpha.*beta"):
        fetch_git_skill(url=f"file://{repo}", subpath="", ref="main")


@pytest.mark.unit
def test_fetch_wrong_subpath_names_candidates(tmp_path) -> None:
    url, _ = _make_repo(tmp_path)
    with pytest.raises(ValueError, match=r"skills/pdf"):
        fetch_git_skill(url=url, subpath="skills/nope", ref="main")


@pytest.mark.unit
def test_fetch_no_skill_md_anywhere(tmp_path) -> None:
    repo = tmp_path / "bare"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("nothing here\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    with pytest.raises(ValueError, match=r"no SKILL\.md anywhere"):
        fetch_git_skill(url=f"file://{repo}", subpath="", ref="main")


@pytest.mark.unit
def test_fetch_git_skill_rejects_non_https_non_file(tmp_path) -> None:
    with pytest.raises(ValueError):
        fetch_git_skill(url="git@github.com:x/y.git", subpath="", ref="main")


@pytest.mark.unit
def test_fetch_git_skill_immutable_sha(tmp_path) -> None:
    """Pinning to sha1 fetches the original commit's content, not the moved tip."""
    url, sha1 = _make_repo(tmp_path)
    repo = tmp_path / "repo"

    # Second commit overwrites SKILL.md with different name + description
    (repo / "skills" / "pdf" / "SKILL.md").write_text(
        '---\nname: pdf-v2\ndescription: "New description"\n---\n# Updated\n'
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "update skill"], repo)

    # Fetch at the pinned original SHA — must see the original content
    out = fetch_git_skill(url=url, subpath="skills/pdf", ref=sha1)

    assert out.pinned_sha == sha1
    assert out.name == "pdf"
    assert out.description == "Edit PDFs"


# ---------------------------------------------------------------------------
# Fix 1: validate derived name at fetch time
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_git_skill_rejects_bad_name(tmp_path) -> None:
    """SKILL.md with an invalid name (uppercase + space) must raise ValueError."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "SKILL.md").write_text(
        '---\nname: "Bad Name"\ndescription: "A fine description"\n---\n# Body\n'
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    url = f"file://{repo}"
    with pytest.raises(ValueError, match="must match"):
        fetch_git_skill(url=url, subpath="", ref="main")


# ---------------------------------------------------------------------------
# list_branches: branch picker for the create form
# ---------------------------------------------------------------------------


def _make_multi_branch_repo(tmp_path):
    """Create a repo (default branch ``main``) with extra branches; return url."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "SKILL.md").write_text('---\nname: x\ndescription: "d"\n---\nb\n')
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    _git(["branch", "dev"], repo)
    _git(["branch", "feature/x"], repo)
    return f"file://{repo}"


@pytest.mark.unit
def test_list_branches_returns_default_first(tmp_path) -> None:
    url = _make_multi_branch_repo(tmp_path)
    branches, default = list_branches(url)
    assert default == "main"
    assert branches == ["main", "dev", "feature/x"]  # default first, rest sorted


@pytest.mark.unit
def test_list_branches_rejects_non_https_non_file(tmp_path) -> None:
    with pytest.raises(ValueError):
        list_branches("git@github.com:x/y.git")


@pytest.mark.unit
def test_list_branches_unreachable_raises(tmp_path) -> None:
    with pytest.raises(ValueError):
        list_branches(f"file://{tmp_path / 'does-not-exist'}")


# ---------------------------------------------------------------------------
# Fix 4: file:// URLs must be rejected in production (flag not set)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_git_skill_rejects_file_url_without_flag(monkeypatch) -> None:
    """file:// skill sources are disabled by default; the autouse fixture sets the
    flag, so we delete it here to test the production guard."""
    monkeypatch.delenv("AGENHOOD_ALLOW_FILE_SKILL_SOURCE", raising=False)
    with pytest.raises(ValueError, match="file://"):
        fetch_git_skill(url="file:///tmp/any-repo", subpath="", ref="main")


# ---------------------------------------------------------------------------
# discover_git_skills: multi-skill repo discovery
# ---------------------------------------------------------------------------

from control_plane.skills_fetch import DiscoveredRepo, discover_git_skills


def _make_multi_skill_repo(tmp_path, specs):
    """Create a repo with one skill dir per (subpath, frontmatter) spec.

    ``specs`` is a list of (subpath, skill_md_text). Returns (url, sha)."""
    repo = tmp_path / "multi"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    for subpath, md in specs:
        d = repo / subpath if subpath else repo
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(md)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return f"file://{repo}", sha


def _md(name, description="d"):
    return f'---\nname: {name}\ndescription: "{description}"\n---\nbody\n'


@pytest.mark.unit
def test_discover_lists_every_skill_sorted_by_subpath(tmp_path) -> None:
    url, sha = _make_multi_skill_repo(tmp_path, [
        ("plugins/suite/skills/writer", _md("writer", "writes")),
        ("plugins/suite/skills/research", _md("research", "researches")),
    ])
    out = discover_git_skills(url=url, ref="main")
    assert isinstance(out, DiscoveredRepo)
    assert out.pinned_sha == sha
    assert out.truncated is False
    assert [s.subpath for s in out.skills] == [
        "plugins/suite/skills/research", "plugins/suite/skills/writer",
    ]
    research = out.skills[0]
    assert (research.name, research.description, research.valid, research.error) == (
        "research", "researches", True, None,
    )


@pytest.mark.unit
def test_discover_single_and_repo_root_skill(tmp_path) -> None:
    url, _ = _make_multi_skill_repo(tmp_path, [("", _md("root-skill"))])
    out = discover_git_skills(url=url, ref="main")
    assert len(out.skills) == 1
    assert out.skills[0].subpath == ""
    assert out.skills[0].name == "root-skill"


@pytest.mark.unit
def test_discover_empty_repo_returns_no_skills(tmp_path) -> None:
    repo = tmp_path / "bare"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("nothing\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    out = discover_git_skills(url=f"file://{repo}", ref="main")
    assert out.skills == []
    assert out.truncated is False


@pytest.mark.unit
def test_discover_broken_frontmatter_is_invalid_but_scan_continues(tmp_path) -> None:
    url, _ = _make_multi_skill_repo(tmp_path, [
        ("bad", "no frontmatter at all\n"),
        ("good", _md("good")),
    ])
    out = discover_git_skills(url=url, ref="main")
    bad = next(s for s in out.skills if s.subpath == "bad")
    good = next(s for s in out.skills if s.subpath == "good")
    assert bad.valid is False and bad.error and bad.name == ""
    assert good.valid is True and good.error is None


@pytest.mark.unit
def test_discover_invalid_name_is_flagged(tmp_path) -> None:
    url, _ = _make_multi_skill_repo(tmp_path, [
        ("bad", '---\nname: "Bad Name"\ndescription: "d"\n---\nb\n'),
    ])
    out = discover_git_skills(url=url, ref="main")
    assert out.skills[0].valid is False
    assert "must match" in (out.skills[0].error or "")


@pytest.mark.unit
def test_discover_duplicate_names_keep_first_flag_rest(tmp_path) -> None:
    url, _ = _make_multi_skill_repo(tmp_path, [
        ("a-dir", _md("same-name")),
        ("b-dir", _md("same-name")),
    ])
    out = discover_git_skills(url=url, ref="main")
    first = next(s for s in out.skills if s.subpath == "a-dir")
    second = next(s for s in out.skills if s.subpath == "b-dir")
    assert first.valid is True
    assert second.valid is False
    assert second.error == "duplicate name in repo"


@pytest.mark.unit
def test_discover_truncates_at_cap(tmp_path) -> None:
    specs = [(f"skills/s{i:03d}", _md(f"skill-{i:03d}")) for i in range(55)]
    url, _ = _make_multi_skill_repo(tmp_path, specs)
    out = discover_git_skills(url=url, ref="main")
    assert len(out.skills) == 50
    assert out.truncated is True


@pytest.mark.unit
def test_discover_pins_by_sha_and_rejects_bad_scheme(tmp_path) -> None:
    url, sha = _make_multi_skill_repo(tmp_path, [("s", _md("s"))])
    out = discover_git_skills(url=url, ref=sha)
    assert out.pinned_sha == sha
    with pytest.raises(ValueError):
        discover_git_skills(url="git@github.com:x/y.git", ref="main")

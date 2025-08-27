from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from shim.git_ops import GitError, GitOps, classify_push_error, redact

pytestmark = pytest.mark.unit


def _git(ws, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ws), *args], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.mark.asyncio
async def test_ensure_repo_creates_repo_with_initial_commit(tmp_path):
    (tmp_path / "hello.txt").write_text("hi")
    ops = GitOps(str(tmp_path))
    info = await ops.ensure_repo()
    assert info == {"created": True, "reinitialized": False}
    assert _git(tmp_path, "log", "--oneline").endswith("initial snapshot")
    # pre-existing files are captured in the baseline
    assert "hello.txt" in _git(tmp_path, "ls-tree", "--name-only", "HEAD")


@pytest.mark.asyncio
async def test_ensure_repo_is_idempotent(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    sha = _git(tmp_path, "rev-parse", "HEAD")
    info = await ops.ensure_repo()
    assert info == {"created": False, "reinitialized": False}
    assert _git(tmp_path, "rev-parse", "HEAD") == sha


@pytest.mark.asyncio
async def test_agent_runtime_dir_is_excluded(tmp_path):
    runtime = tmp_path / ".agent-runtime"
    runtime.mkdir()
    (runtime / "auth.json").write_text("{\"secret\": true}")
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    tracked = _git(tmp_path, "ls-files")
    assert ".agent-runtime" not in tracked


@pytest.mark.asyncio
async def test_agent_runtime_excluded_in_repo_the_shim_did_not_create(tmp_path):
    """Agents may run ``git init`` in the workspace themselves (visible .git
    is by design) and rehydrated volumes can carry a pre-existing repo. Such
    a repo is healthy, so ensure_repo() short-circuits without ever writing
    .git/info/exclude — commit_all/push must STILL never ship the codex OAuth
    secrets in .agent-runtime."""
    ws = tmp_path / "ws"
    runtime = ws / ".agent-runtime" / "codex"
    runtime.mkdir(parents=True)
    (runtime / "auth.json").write_text('{"access_token": "oauth-secret"}')
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.name", "Agent")
    _git(ws, "config", "user.email", "agent@example.com")
    _git(ws, "commit", "--allow-empty", "-m", "agent-created repo")

    ops = GitOps(str(ws))
    assert await ops.ensure_repo() == {"created": False, "reinitialized": False}
    (ws / "work.txt").write_text("task output")
    sha = await ops.commit_all("task tsk_1: completed")
    assert sha is not None
    tracked = _git(ws, "ls-tree", "-r", "--name-only", "HEAD")
    assert "work.txt" in tracked
    assert ".agent-runtime" not in tracked

    # ...so the pushed HEAD never contains the secret either
    bare = _make_bare(tmp_path)
    # Updated: push now takes ssh_private_key= instead of token=
    assert await ops.push(url=bare, ssh_private_key="FAKE-KEY", branch="main") == sha
    assert ".agent-runtime" not in _git(bare, "ls-tree", "-r", "--name-only", "main")


@pytest.mark.asyncio
async def test_agent_tracked_runtime_secrets_are_dropped_not_committed(tmp_path):
    """info/exclude only shields UNtracked paths. If the agent recreates the
    repo and runs ``git add -A && git commit`` itself, auth.json is already
    tracked when the shim next touches the repo — commit_all must untrack it
    (keeping the live file on disk) instead of snapshotting the secret into
    every future commit and push."""
    ws = tmp_path / "ws"
    runtime = ws / ".agent-runtime" / "codex"
    runtime.mkdir(parents=True)
    (runtime / "auth.json").write_text('{"access_token": "oauth-secret"}')
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.name", "Agent")
    _git(ws, "config", "user.email", "agent@example.com")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-m", "agent-created repo")
    assert ".agent-runtime/codex/auth.json" in _git(ws, "ls-files")

    ops = GitOps(str(ws))
    (ws / "work.txt").write_text("task output")
    sha = await ops.commit_all("task tsk_1: completed")
    assert sha is not None
    tracked = _git(ws, "ls-tree", "-r", "--name-only", "HEAD")
    assert "work.txt" in tracked
    assert ".agent-runtime" not in tracked
    # the live credential file is untouched on disk (codex keeps working)
    assert (runtime / "auth.json").read_text() == '{"access_token": "oauth-secret"}'
    # once dropped it stays dropped: a clean worktree is a no-op again
    assert await ops.commit_all("task tsk_2: completed") is None


@pytest.mark.asyncio
async def test_rollback_untracks_runtime_secrets_and_keeps_them_on_disk(tmp_path):
    """If the agent force-added .agent-runtime, a rollback to a clean tree
    must not ``reset --hard`` the live codex credentials out of the worktree,
    and the rollback commit's tree must not contain them either."""
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "f.txt").write_text("v1")
    sha_v1 = await ops.commit_all("task tsk_1: completed")
    runtime = tmp_path / ".agent-runtime" / "codex"
    runtime.mkdir(parents=True)
    (runtime / "auth.json").write_text('{"access_token": "oauth-secret"}')
    _git(tmp_path, "add", "-f", ".agent-runtime")      # agent bypasses exclude
    _git(tmp_path, "commit", "-m", "agent tracked secrets")
    (tmp_path / "f.txt").write_text("v2")

    new_sha = await ops.rollback(sha_v1)

    assert (tmp_path / "f.txt").read_text() == "v1"
    assert (runtime / "auth.json").read_text() == '{"access_token": "oauth-secret"}'
    assert ".agent-runtime" not in _git(
        tmp_path, "ls-tree", "-r", "--name-only", new_sha)


@pytest.mark.asyncio
async def test_corrupt_repo_is_reinitialized(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    shutil.rmtree(tmp_path / ".git")
    (tmp_path / ".git").write_text("not a repo")   # agent damage
    info = await ops.ensure_repo()
    assert info == {"created": False, "reinitialized": True}
    assert _git(tmp_path, "log", "--oneline").endswith("repository reinitialized")


@pytest.mark.asyncio
async def test_repo_status(tmp_path):
    ops = GitOps(str(tmp_path))
    status = await ops.repo_status()       # lazily initializes
    assert status["initialized"] is True
    assert status["dirty"] is False
    (tmp_path / "new.txt").write_text("x")
    status = await ops.repo_status()
    assert status["dirty"] is True
    assert len(status["head"]) == 40


@pytest.mark.asyncio
async def test_commit_all_creates_snapshot_and_skips_noop(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "a.txt").write_text("v1")
    sha = await ops.commit_all("task tsk_1: completed")
    assert sha is not None and len(sha) == 40
    # nothing changed -> no commit
    assert await ops.commit_all("task tsk_2: completed") is None
    # deletions are captured too
    (tmp_path / "a.txt").unlink()
    assert await ops.commit_all("task tsk_3: completed") is not None


@pytest.mark.asyncio
async def test_log_entries_parses_task_ids_and_file_counts(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "a.txt").write_text("v1")
    (tmp_path / "b.txt").write_text("v1")
    await ops.commit_all("task tsk_1: completed")
    entries = await ops.log_entries()
    assert len(entries) == 2                       # task commit + initial
    top = entries[0]
    assert top["task_id"] == "tsk_1"
    assert top["files_changed"] == 2
    assert top["message"] == "task tsk_1: completed"
    assert isinstance(top["ts"], int)
    assert entries[1]["task_id"] is None           # "initial snapshot"


@pytest.mark.asyncio
async def test_rollback_restores_content_with_linear_history(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "f.txt").write_text("v1")
    sha_v1 = await ops.commit_all("task tsk_1: completed")
    (tmp_path / "f.txt").write_text("v2")
    (tmp_path / "extra.txt").write_text("x")
    await ops.commit_all("task tsk_2: completed")

    new_sha = await ops.rollback(sha_v1)

    assert (tmp_path / "f.txt").read_text() == "v1"
    assert not (tmp_path / "extra.txt").exists()
    entries = await ops.log_entries()
    assert entries[0]["sha"] == new_sha
    assert entries[0]["message"].startswith("rollback to ")
    assert len(entries) == 4                      # nothing destroyed: initial, v1, v2, rollback


@pytest.mark.asyncio
async def test_rollback_of_rollback_returns_to_v2(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "f.txt").write_text("v1")
    sha_v1 = await ops.commit_all("task tsk_1: completed")
    (tmp_path / "f.txt").write_text("v2")
    sha_v2 = await ops.commit_all("task tsk_2: completed")
    await ops.rollback(sha_v1)
    await ops.rollback(sha_v2)
    assert (tmp_path / "f.txt").read_text() == "v2"


@pytest.mark.asyncio
async def test_rollback_snapshots_dirty_worktree_first(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    (tmp_path / "f.txt").write_text("v1")
    sha_v1 = await ops.commit_all("task tsk_1: completed")
    (tmp_path / "uploaded.txt").write_text("manual upload")   # uncommitted
    await ops.rollback(sha_v1)
    entries = await ops.log_entries()
    # the dirty state was preserved as its own snapshot before rolling back
    assert any(e["message"] == "pre-rollback snapshot" for e in entries)
    assert not (tmp_path / "uploaded.txt").exists()


@pytest.mark.asyncio
async def test_rollback_unknown_sha_raises(tmp_path):
    ops = GitOps(str(tmp_path))
    await ops.ensure_repo()
    with pytest.raises(GitError) as exc:
        await ops.rollback("0" * 40)
    assert exc.value.code == "unknown_sha"


def _make_bare(tmp_path) -> str:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    return str(bare)


@pytest.mark.asyncio
async def test_push_mirrors_head_to_remote_branch(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ops = GitOps(str(ws))
    await ops.ensure_repo()
    (ws / "f.txt").write_text("v1")
    sha = await ops.commit_all("task tsk_1: completed")
    bare = _make_bare(tmp_path)

    # Updated: push now takes ssh_private_key= instead of token=
    pushed = await ops.push(url=bare, ssh_private_key="FAKE-KEY", branch="main")

    assert pushed == sha
    assert _git(bare, "rev-parse", "main") == sha
    # pushing again with no new commits is a no-op success
    assert await ops.push(url=bare, ssh_private_key="FAKE-KEY", branch="main") == sha


@pytest.mark.asyncio
async def test_push_never_writes_remote_or_key_into_config(tmp_path):
    # Renamed from test_push_never_writes_remote_or_token_into_config;
    # askpass helper no longer used (SSH replaces HTTPS token auth).
    ws = tmp_path / "ws"
    ws.mkdir()
    ops = GitOps(str(ws))
    await ops.ensure_repo()
    bare = _make_bare(tmp_path)
    # Updated: push now takes ssh_private_key= instead of token=
    await ops.push(url=bare, ssh_private_key="FAKE-KEY", branch="main")
    config = (ws / ".git" / "config").read_text()
    assert "FAKE-KEY" not in config
    assert bare not in config                      # remote URL not persisted
    # key is written transiently to .agent-runtime (not .agent-state) and
    # removed after the push — no persistent key file in the workspace
    key_dir = ws / ".agent-runtime" / "ssh"
    leftover_keys = [p for p in key_dir.iterdir() if p.name.startswith("id_")]
    assert leftover_keys == []                     # key cleaned up post-push


@pytest.mark.asyncio
async def test_verify_remote_ok_and_failure(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ops = GitOps(str(ws))
    # Updated: verify_remote now takes ssh_private_key= (not token=) and
    # returns a {branches, default_branch} dict (not None).
    bare = _make_bare(tmp_path)
    result = await ops.verify_remote(url=bare, ssh_private_key="FAKE-KEY")
    assert isinstance(result, dict)
    assert "branches" in result
    assert "default_branch" in result
    with pytest.raises(GitError):
        await ops.verify_remote(url=str(tmp_path / "missing.git"), ssh_private_key="FAKE-KEY")


# ---------------------------------------------------------------------------
# Part A: branch parsing + key material
# ---------------------------------------------------------------------------


def test_parse_ls_remote_heads():
    from shim.git_ops import parse_ls_remote_branches
    out = (
        "ref: refs/heads/main\tHEAD\n"
        "abc123\trefs/heads/main\n"
        "def456\trefs/heads/feature/x\n"
        "999\trefs/tags/v1\n"
    )
    branches, default = parse_ls_remote_branches(out)
    assert branches == ["main", "feature/x"]
    assert default == "main"


def test_remote_host_extracts_host():
    from shim.git_ops import _remote_host
    assert _remote_host("git@github.com:a/b.git") == "github.com"
    assert _remote_host("ssh://git@gitlab.com:2222/g/r.git") == "gitlab.com"


def test_write_key_material_is_root_only_0600(tmp_path):
    import os

    from shim.git_ops import GitOps
    ops = GitOps(str(tmp_path))
    key_path, kh = ops._write_key_material("PRIVATE-KEY-DATA")
    assert "/.agent-runtime/" in key_path        # root-only tree, NOT .agent-state
    assert "/.agent-state/" not in key_path
    assert oct(os.stat(key_path).st_mode)[-3:] == "600"
    assert os.path.exists(kh)
    os.remove(key_path)


# ---------------------------------------------------------------------------
# Part B: error classification
# ---------------------------------------------------------------------------


def test_classify_remote_error_codes():
    from shim.git_ops import classify_remote_error
    assert classify_remote_error("Permission denied (publickey).") == "auth_failed"
    assert classify_remote_error("Host key verification failed.") == "host_key_changed"
    assert classify_remote_error("Could not resolve host: x") == "host_unreachable"
    assert classify_remote_error("repository not found") == "repo_not_found"
    assert classify_remote_error("! [rejected] main -> main (non-fast-forward)") == "push_rejected"
    assert classify_remote_error("weird") == "push_failed"


def test_classify_push_error():
    # classify_push_error is an alias for classify_remote_error; error codes
    # updated to reflect the new SSH-oriented classification scheme.
    assert classify_push_error("fatal: Authentication failed for ...") == "auth_failed"
    assert classify_push_error("The requested URL returned error: 403") == "egress_blocked"
    assert classify_push_error("! [rejected] main -> main (fetch first)") == "push_rejected"
    assert (
        classify_push_error("fatal: unable to access 'x': Could not resolve host")
        == "host_unreachable"
    )
    assert classify_push_error("something exotic") == "push_failed"


def test_redact():
    assert redact("error with ghp_abc in it", "ghp_abc") == "error with *** in it"
    assert redact("text", "") == "text"


def test_exclude_lists_both_runtime_dirs(tmp_path):
    ops = GitOps(str(tmp_path))
    asyncio.run(ops.ensure_repo())
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text()
    assert ".agent-runtime/" in exclude
    assert ".agent-state/" in exclude


def test_build_ssh_command_includes_proxy_and_key():
    from shim.git_ops import build_ssh_command
    cmd = build_ssh_command(
        key_path="/run/k", known_hosts="/run/kh",
        host="github.com", proxy="egress-proxy:8888",
    )
    assert "/run/k" in cmd
    assert "ProxyCommand=" in cmd
    assert "github.com" in cmd            # CONNECT target host
    assert "egress-proxy:8888" in cmd
    assert "UserKnownHostsFile=/run/kh" in cmd
    assert "StrictHostKeyChecking=accept-new" in cmd
    assert "BatchMode=yes" in cmd


def test_build_ssh_command_without_proxy_omits_proxycommand():
    from shim.git_ops import build_ssh_command
    cmd = build_ssh_command(key_path="/k", known_hosts="/kh", host="h", proxy=None)
    assert "ProxyCommand" not in cmd
    assert "/k" in cmd


def test_build_ssh_command_proxycommand_is_single_shell_token():
    """GIT_SSH_COMMAND is shell-split by git before exec; the ProxyCommand value
    must survive as one token so ssh receives 'ProxyCommand=nc …' as a single
    -o argument, not as 'ProxyCommand=nc' plus stray words."""
    import shlex

    from shim.git_ops import build_ssh_command

    cmd = build_ssh_command(
        key_path="/k", known_hosts="/kh",
        host="github.com", proxy="egress-proxy:8888",
    )
    toks = shlex.split(cmd)
    # find the -o ProxyCommand=... token (the value after the -o flag)
    pc = [t for t in toks if t.startswith("ProxyCommand=")]
    assert len(pc) == 1, f"expected exactly one ProxyCommand token, got: {pc}"
    assert pc[0] == "ProxyCommand=nc -X connect -x egress-proxy:8888 github.com 22"
    # key and host present in the ProxyCommand value
    assert "github.com" in pc[0]
    assert "egress-proxy:8888" in pc[0]


def test_ls_remote_lists_branches_from_local_bare_repo(tmp_path):
    import asyncio
    import os
    import subprocess

    from shim.git_ops import GitOps

    # A bare remote with two branches, default = main.
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True,
    )
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (work / "f.txt").write_text("hi")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "init"], check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "-C", str(work), "branch", "dev"], check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "-C", str(work), "remote", "add", "origin", str(bare)],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "main", "dev"],
        check=True, capture_output=True, env=env,
    )

    ws = tmp_path / "ws"
    os.makedirs(ws, exist_ok=True)
    ops = GitOps(str(ws))
    res = asyncio.run(ops.ls_remote(url=str(bare), ssh_private_key="UNUSED-FOR-LOCAL"))
    assert set(res["branches"]) == {"main", "dev"}
    assert res["default_branch"] == "main"


@pytest.mark.asyncio
async def test_git_child_env_never_contains_shim_token(tmp_path, monkeypatch):
    """Regression: git child processes must not inherit SHIM_TOKEN from the shim
    environment.  The build_child_env allowlist must be the only source of env
    vars for every git subprocess, even though git runs dropped to the agent uid."""
    captured: list[dict[str, str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setenv("SHIM_TOKEN", "super-secret-token")
    monkeypatch.setattr("shim.git_ops.subprocess.run", fake_run)

    ops = GitOps(str(tmp_path))
    await ops._git("rev-parse", "HEAD")

    assert captured, "subprocess.run was never called"
    env = captured[0]
    assert "SHIM_TOKEN" not in env, "SHIM_TOKEN leaked into git subprocess env"
    assert "PATH" in env, "PATH must be forwarded to git subprocess"


def _make_bare_remote(tmp_path, branch="main"):
    """Create a bare remote repo with one commit on <branch>; return its path."""
    work = tmp_path / "remote-work"
    work.mkdir()
    subprocess.run(["git", "-C", str(work), "init", "-b", branch], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True, capture_output=True)
    (work / "README.md").write_text("from remote\n")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "remote init"], check=True, capture_output=True)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(work), str(bare)], check=True, capture_output=True)
    return bare


@pytest.mark.asyncio
async def test_clone_replaces_files_and_preserves_reserved(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "old.txt").write_text("stale workspace file")
    runtime = ws / ".agent-runtime"
    runtime.mkdir()
    (runtime / "secret").write_text("keep me")
    state = ws / ".agent-state"
    state.mkdir()
    (state / "home").write_text("keep me too")

    bare = _make_bare_remote(tmp_path)
    ops = GitOps(str(ws))
    sha = await ops.clone(url=str(bare), ssh_private_key="", branch="main")

    assert len(sha) == 40
    # remote content is now present, the old workspace file is gone
    assert (ws / "README.md").read_text() == "from remote\n"
    assert not (ws / "old.txt").exists()
    # shim-private dirs survived the wipe
    assert (runtime / "secret").read_text() == "keep me"
    assert (state / "home").read_text() == "keep me too"
    # origin is set to the remote (agent/harness now owns git)
    assert str(bare) in _git(ws, "remote", "get-url", "origin")


@pytest.mark.asyncio
async def test_clone_does_not_destroy_workspace_on_failure(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "keep.txt").write_text("still here")
    ops = GitOps(str(ws))
    with pytest.raises(GitError):
        await ops.clone(
            url=str(tmp_path / "does-not-exist.git"), ssh_private_key="", branch="main",
        )
    # the failed clone never touched the existing workspace
    assert (ws / "keep.txt").read_text() == "still here"


@pytest.mark.asyncio
async def test_clone_provisions_agent_push_key(tmp_path):
    """The deploy key is persisted agent-readably under .agent-state/git and
    wired into core.sshCommand so the agent can push later (pull mode)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    bare = _make_bare_remote(tmp_path)
    ops = GitOps(str(ws))
    await ops.clone(url=str(bare), ssh_private_key="PRIVATE-KEY-DATA", branch="main")

    key = ws / ".agent-state" / "git" / "deploy_key"
    # key persisted (NOT deleted) with the exact material, so the agent can push
    assert key.read_text() == "PRIVATE-KEY-DATA\n"
    # 0600 perms on the private key
    assert (key.stat().st_mode & 0o777) == 0o600
    # repo is wired to use that key for the agent's pushes
    ssh_cmd = _git(ws, "config", "core.sshCommand")
    assert str(key) in ssh_cmd
    assert "IdentitiesOnly=yes" in ssh_cmd
    # known_hosts is provisioned 0600 alongside the key (host-key TOFU on push)
    kh = ws / ".agent-state" / "git" / "known_hosts"
    assert kh.exists()
    assert (kh.stat().st_mode & 0o777) == 0o600
    # the key dir is excluded from the workspace (never committed/pushed/listed)
    exclude = (ws / ".git" / "info" / "exclude").read_text()
    assert ".agent-state/" in exclude

    # re-pull / relink overwrites the key with the new material (idempotent)
    await ops.clone(url=str(bare), ssh_private_key="ROTATED-KEY", branch="main")
    assert key.read_text() == "ROTATED-KEY\n"
    assert (key.stat().st_mode & 0o777) == 0o600

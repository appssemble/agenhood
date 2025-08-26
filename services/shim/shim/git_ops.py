"""Git plumbing for the workspace (workspace git rollback spec).

All operations shell out to the ``git`` binary already present in the agent
image. Every public method health-checks the repo first and re-initializes a
missing/corrupt repo — the agent can see (and damage) ``.git``. Operations are
serialized behind one asyncio.Lock so a rollback can never race the post-task
auto-commit.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from agentcore import sandbox

COMMIT_TIMEOUT = 60.0
PUSH_TIMEOUT = 120.0
VERIFY_TIMEOUT = 30.0

_COMMITTER_NAME = "Agenhood"
_COMMITTER_EMAIL = "agent@agenhood"

_TASK_RE = re.compile(r"^task (\S+): ")
_STAT_RE = re.compile(r"(\d+) files? changed")

# SSH over the egress proxy: ssh's ProxyCommand opens a raw tunnel by speaking
# the proxy's CONNECT verb, then SSH runs over it. The proxy accepts any port.
_PROXY_AUTHORITY_ENV = "EGRESS_SSH_PROXY"  # optional override; else derive from HTTP(S)_PROXY

# ls-remote output parsing
_DEFAULT_HEAD_RE = re.compile(r"^ref:\s+refs/heads/(?P<b>\S+)\s+HEAD$")
_HEAD_RE = re.compile(r"^[0-9a-f]+\s+refs/heads/(?P<b>\S+)$")
_SCP_RE = re.compile(r"^(?P<user>[^@/]+@)?(?P<host>[^/:]+):(?P<path>.*)$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+$")


def parse_ls_remote_branches(out: str) -> tuple[list[str], str | None]:
    """Parse `git ls-remote --symref <url> heads` → (branch names, default)."""
    branches: list[str] = []
    default: str | None = None
    for raw in out.splitlines():
        line = raw.rstrip()
        m = _DEFAULT_HEAD_RE.match(line)
        if m:
            default = m.group("b")
            continue
        m = _HEAD_RE.match(line)
        if m:
            branches.append(m.group("b"))
    return branches, default


def _remote_host(url: str) -> str:
    url = url.strip()
    if url.startswith("ssh://"):
        rest = url[len("ssh://"):]
        authority = rest.split("/", 1)[0]
        return authority.rsplit("@", 1)[-1].split(":", 1)[0]
    m = _SCP_RE.match(url)
    return m.group("host") if m else ""


def proxy_authority() -> str | None:
    """host:port for the egress proxy, derived from HTTP(S)_PROXY (or override).

    Both sources are infra-controlled env vars (not user input), so the value
    is trusted for interpolation into ProxyCommand.
    """
    override = os.environ.get(_PROXY_AUTHORITY_ENV)
    if override:
        return override
    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
    raw = raw.replace("http://", "").replace("https://", "").strip("/")
    return raw or None


def build_ssh_command(
    *, key_path: str, known_hosts: str, host: str, proxy: str | None,
) -> str:
    """The GIT_SSH_COMMAND value: identity-only ssh, host-key TOFU, optional
    proxy tunnel via the egress proxy's CONNECT verb."""
    if host and not _HOST_RE.match(host):
        raise ValueError("invalid ssh host")
    parts = [
        "ssh", "-i", key_path,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
        f"-o UserKnownHostsFile={known_hosts}",
    ]
    if proxy:
        # %h/%p would be the target; we hardcode port 22 to the resolved host.
        # `nc -X connect -x <proxy> <host> 22` speaks HTTP CONNECT to the proxy.
        # The VALUE is double-quoted so GIT_SSH_COMMAND shell-splitting (done by
        # git before exec) keeps "nc … 22" as a single ProxyCommand token.
        parts += ["-o", f'ProxyCommand="nc -X connect -x {proxy} {host} 22"']
    return " ".join(parts)


class GitError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def classify_remote_error(stderr: str) -> str:
    """Map git remote operation stderr to a stable error code."""
    s = stderr.lower()
    if ("permission denied" in s or "authentication failed" in s
            or "publickey" in s or "access denied" in s):
        return "auth_failed"
    if "host key verification failed" in s or "remote host identification" in s:
        return "host_key_changed"
    if ("could not resolve host" in s or "name or service not known" in s
            or "connection" in s or "timed out" in s or "unable to access" in s):
        return "host_unreachable"
    if "repository not found" in s or "does not exist" in s:
        return "repo_not_found"
    if "[rejected]" in s or "non-fast-forward" in s or "fetch first" in s:
        return "push_rejected"
    if "403" in s or "blocked" in s:
        return "egress_blocked"
    return "push_failed"


classify_push_error = classify_remote_error  # back-compat alias


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


class GitOps:
    def __init__(self, workspace: str) -> None:
        self.workspace = workspace
        self._lock = asyncio.Lock()

    # ---- low-level -----------------------------------------------------

    async def _git(
        self, *args: str,
        env: dict[str, str] | None = None,
        timeout: float = COMMIT_TIMEOUT,  # noqa: ASYNC109 — subprocess.run kills on timeout
        privileged: bool = False,
    ) -> tuple[int, str, str]:
        # Deliberately thread-based (not asyncio.create_subprocess_exec): git
        # runs post-task in background asyncio tasks, and CPython's subprocess
        # transports can deadlock event-loop teardown when such a task is
        # cancelled mid-spawn (`_make_subprocess_transport` awaits an exit
        # notification whose `_connect_pipes` helper task was also cancelled).
        # A worker thread always finishes, bounded by `timeout`.
        full_env = sandbox.build_child_env({**(env or {}), "GIT_TERMINAL_PROMPT": "0"})

        def _run() -> subprocess.CompletedProcess[bytes]:
            drop = {} if privileged else sandbox.drop_kwargs()
            return subprocess.run(  # noqa: S603 — fixed binary, args from code
                ["git", "-C", self.workspace, *args],
                capture_output=True, env=full_env, timeout=timeout, **drop,
            )

        try:
            proc = await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            raise GitError("git_timeout", f"git {args[0]} timed out") from None
        return (proc.returncode or 0,
                proc.stdout.decode(errors="replace"),
                proc.stderr.decode(errors="replace"))

    async def _head(self) -> str:
        rc, out, err = await self._git("rev-parse", "HEAD")
        if rc != 0:
            raise GitError("git_failed", err)
        return out.strip()

    async def _healthy(self) -> bool:
        if not os.path.isdir(os.path.join(self.workspace, ".git")):
            return False
        rc, _, _ = await self._git("rev-parse", "HEAD")
        return rc == 0

    def _assert_runtime_exclude(self) -> None:
        """Idempotently (re)write the runtime-dir exclusions.

        .agent-runtime (shim-private) and .agent-state (driver homes + codex
        auth.json / opencode oauth tokens) must NEVER be committed or pushed.
        The repo may be healthy without the shim ever having initialized it
        (the agent is allowed to run ``git init`` in the workspace;
        resumed/rehydrated volumes can carry a pre-existing repo), so the
        excludes must be asserted on every operation — not only when
        ``_ensure_repo_locked`` rebuilds the repo.
        """
        wanted = (".agent-runtime/", ".agent-state/")
        exclude = os.path.join(self.workspace, ".git", "info", "exclude")
        existing: set[str] = set()
        try:
            with open(exclude, encoding="utf-8") as fh:
                existing = {line.strip() for line in fh}
        except FileNotFoundError:
            pass
        missing = [w for w in wanted if w not in existing]
        if not missing:
            return
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(missing) + "\n")

    async def _untrack_runtime(self) -> None:
        """Drop already-tracked ``.agent-runtime`` files from the index.

        ``info/exclude`` only shields UNtracked paths: if the agent committed
        the runtime dir itself (e.g. it recreated the repo and ran ``git add
        -A`` before any shim operation could re-assert the exclude), every
        subsequent ``git add -A`` would keep snapshotting the codex OAuth
        tokens — and ``rollback``'s ``reset --hard`` would even delete the
        live credential files from the worktree. ``--cached`` removes the
        paths from the index only, so the next auto-commit drops the secrets
        from the tree while the files on disk stay untouched.
        """
        rc, _, err = await self._git(
            "rm", "-r", "-q", "--cached", "--ignore-unmatch",
            "--", ".agent-runtime", ".agent-state",
        )
        if rc != 0:
            raise GitError("git_failed", err)

    async def _ensure_repo_locked(self) -> dict[str, Any]:
        if await self._healthy():
            self._assert_runtime_exclude()
            return {"created": False, "reinitialized": False}
        git_dir = os.path.join(self.workspace, ".git")
        reinit = os.path.exists(git_dir)
        if os.path.isdir(git_dir):
            shutil.rmtree(git_dir, ignore_errors=True)
        elif os.path.exists(git_dir):
            os.remove(git_dir)
        rc, _, err = await self._git("init", "-b", "main")
        if rc != 0:
            raise GitError("git_init_failed", err)
        await self._git("config", "user.name", _COMMITTER_NAME)
        await self._git("config", "user.email", _COMMITTER_EMAIL)
        # Exclude secrets without polluting the visible workspace with a
        # .gitignore (see _assert_runtime_exclude).
        self._assert_runtime_exclude()
        msg = "repository reinitialized" if reinit else "initial snapshot"
        await self._git("add", "-A")
        rc, _, err = await self._git("commit", "--allow-empty", "-m", msg)
        if rc != 0:
            raise GitError("git_commit_failed", err)
        return {"created": not reinit, "reinitialized": reinit}

    # ---- SSH key material ----------------------------------------------

    def _key_dir(self) -> str:
        # Root-only shim-private tree — NEVER .agent-state (agent-readable).
        return os.path.join(self.workspace, ".agent-runtime", "ssh")

    def _write_key_material(self, private_key: str) -> tuple[str, str]:
        """Write the private key + a known_hosts file (0600) under .agent-runtime.
        Returns (key_path, known_hosts_path). Caller removes the key when done."""
        d = self._key_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        fd, key_path = tempfile.mkstemp(prefix="id_", dir=d)
        with os.fdopen(fd, "w") as fh:
            fh.write(private_key if private_key.endswith("\n") else private_key + "\n")
        os.chmod(key_path, 0o600)
        known_hosts = os.path.join(d, "known_hosts")
        if not os.path.exists(known_hosts):
            open(known_hosts, "a").close()  # noqa: SIM115 — intentional touch
        os.chmod(known_hosts, 0o600)
        return key_path, known_hosts

    def _ssh_env(self, url: str, key_path: str, known_hosts: str) -> dict[str, str]:
        cmd = build_ssh_command(
            key_path=key_path, known_hosts=known_hosts,
            host=_remote_host(url), proxy=proxy_authority(),
        )
        return {"GIT_SSH_COMMAND": cmd}

    # ---- persistent push key (linked / pull mode) ----------------------

    def _push_key_dir(self) -> str:
        # Agent-READABLE (unlike .agent-runtime, which is root-only): in linked
        # mode the agent runs ``git push`` itself, so it must be able to read the
        # deploy key. Lives under .agent-state — already excluded from commits and
        # the file API, like the driver credentials kept there.
        return os.path.join(self.workspace, ".agent-state", "git")

    def _install_push_key(self, private_key: str, url: str) -> tuple[str, str, str]:
        """Persist the deploy key + known_hosts agent-readably and build the ssh
        command (identity-only, host-key TOFU, egress proxy). Returns
        (key_path, known_hosts, ssh_command). The same key/command drive this
        clone and the agent's later pushes (wired via core.sshCommand)."""
        # .agent-state must be agent-traversable so the dropped agent can reach
        # the key dir; ensure_agent_dir chowns to the agent uid when we are root.
        sandbox.ensure_agent_dir(os.path.join(self.workspace, ".agent-state"), mode=0o700)
        d = self._push_key_dir()
        sandbox.ensure_agent_dir(d, mode=0o700)
        key_path = os.path.join(d, "deploy_key")
        data = private_key if private_key.endswith("\n") else private_key + "\n"
        # Create 0600 atomically (no umask-dependent world/group-readable window),
        # then re-assert perms + agent ownership.
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(data)
        os.chmod(key_path, 0o600)
        sandbox.chown_to_agent(key_path)
        known_hosts = os.path.join(d, "known_hosts")
        if not os.path.exists(known_hosts):
            open(known_hosts, "a").close()  # noqa: SIM115 — intentional touch
        os.chmod(known_hosts, 0o600)
        sandbox.chown_to_agent(known_hosts)
        cmd = build_ssh_command(
            key_path=key_path, known_hosts=known_hosts,
            host=_remote_host(url), proxy=proxy_authority(),
        )
        return key_path, known_hosts, cmd

    def _chown_push_key_dir(self) -> None:
        """Re-assert agent ownership of the key dir: the privileged clone runs as
        root and may (re)write known_hosts root-owned, which the agent could then
        not read on push."""
        for root, _dirs, files in os.walk(self._push_key_dir()):
            sandbox.chown_to_agent(root)
            for f in files:
                sandbox.chown_to_agent(os.path.join(root, f))

    # ---- public --------------------------------------------------------

    async def ensure_repo(self) -> dict[str, Any]:
        async with self._lock:
            return await self._ensure_repo_locked()

    async def repo_status(self) -> dict[str, Any]:
        async with self._lock:
            info = await self._ensure_repo_locked()
            head = await self._head()
            _, out, _ = await self._git("status", "--porcelain")
            return {
                "initialized": True,
                "head": head,
                "dirty": bool(out.strip()),
                "reinitialized": info["reinitialized"],
            }

    async def commit_all(self, message: str) -> str | None:
        """Commit the whole worktree. Returns the new sha, or None if clean."""
        async with self._lock:
            await self._ensure_repo_locked()
            await self._untrack_runtime()
            rc, _, err = await self._git("add", "-A")
            if rc != 0:
                raise GitError("git_add_failed", err)
            _, out, _ = await self._git("status", "--porcelain")
            if not out.strip():
                return None
            rc, _, err = await self._git("commit", "-m", message)
            if rc != 0:
                raise GitError("git_commit_failed", err)
            return await self._head()

    async def rollback(self, sha: str) -> str:
        """Create a NEW commit whose tree is ``sha``'s tree (revert-commit
        semantics): never conflicts, history stays linear, no force-push."""
        async with self._lock:
            await self._ensure_repo_locked()
            rc, _, _ = await self._git("cat-file", "-e", f"{sha}^{{commit}}")
            if rc != 0:
                raise GitError("unknown_sha", f"no commit {sha}")
            # Untrack secrets BEFORE the reset --hard below: if .agent-runtime
            # were tracked, resetting to a tree without it would delete the
            # live codex credentials from the worktree.
            await self._untrack_runtime()
            # Preserve any uncommitted changes (e.g. console file uploads) as
            # their own snapshot so rollback never silently destroys work.
            _, out, _ = await self._git("status", "--porcelain")
            if out.strip():
                await self._git("add", "-A")
                rc, _, err = await self._git("commit", "-m", "pre-rollback snapshot")
                if rc != 0:
                    raise GitError("git_commit_failed", err)
            _, short, _ = await self._git("rev-parse", "--short", sha)
            head = await self._head()
            rc, new_sha, err = await self._git(
                "commit-tree", f"{sha}^{{tree}}", "-p", head,
                "-m", f"rollback to {short.strip()}",
            )
            if rc != 0:
                raise GitError("git_failed", err)
            new_sha = new_sha.strip()
            rc, _, err = await self._git("reset", "--hard", new_sha)
            if rc != 0:
                raise GitError("git_failed", err)
            return new_sha

    _RESERVED = (".agent-runtime", ".agent-state")

    async def clone(self, *, url: str, ssh_private_key: str, branch: str) -> str:
        """One-time clone of <branch> into the workspace (pull mode).

        Clone into a temp dir FIRST so a failed network clone never destroys the
        existing workspace; only on success wipe the workspace (preserving the
        shim-private reserved dirs) and move the clone in. After this the agent
        and harness own the workspace .git (origin points at <url>).

        The deploy key is installed PERSISTENTLY under .agent-state/git (agent-
        readable, never committed) and wired into the repo's core.sshCommand, so
        the agent can ``git push`` to the remote when its deploy key was granted
        write access. .agent-state is excluded from commits and the file API.
        """
        async with self._lock:
            # Install the persistent, agent-readable deploy key + an ssh command
            # routed over the egress proxy. Drives THIS clone and (via
            # core.sshCommand below) the agent's later pushes.
            _, _, ssh_cmd = self._install_push_key(ssh_private_key, url)
            env = {"GIT_SSH_COMMAND": ssh_cmd}

            # Place the temp clone dir INSIDE the workspace's .agent-runtime so it
            # is on the SAME filesystem as the workspace (shutil.move below becomes
            # a cheap rename, not a cross-device copy+unlink) and lands in a dir the
            # wipe loop and _chown_tree_to_agent already skip (it's in _RESERVED).
            runtime_dir = os.path.join(self.workspace, ".agent-runtime")
            os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
            tmp = tempfile.mkdtemp(prefix="clone_", dir=runtime_dir)
            try:
                dest = os.path.join(tmp, "repo")
                rc, _, err = await self._git(
                    "clone", "--branch", branch, "--single-branch", url, dest,
                    env=env, timeout=PUSH_TIMEOUT, privileged=True,
                )
                if rc != 0:
                    raise GitError(classify_remote_error(err), redact(err, ssh_private_key))

                # Clone succeeded — now it is safe to replace the workspace.
                for name in os.listdir(self.workspace):
                    if name in self._RESERVED:
                        continue
                    p = os.path.join(self.workspace, name)
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                for name in os.listdir(dest):
                    shutil.move(os.path.join(dest, name), os.path.join(self.workspace, name))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            self._assert_runtime_exclude()
            # Hand the freshly cloned tree to the agent FIRST. The privileged
            # clone left .git (and the key dir) root-owned; the git config writes
            # below run dropped to the agent uid, so they would fail silently on a
            # root-owned .git/config unless we chown it to the agent first.
            self._chown_push_key_dir()
            self._chown_tree_to_agent()
            # Now .git is agent-writable: identity for future commits, and the
            # deploy key (via core.sshCommand) so the agent's pushes route over
            # the egress proxy. Fail loudly if the push wiring doesn't stick.
            await self._git("config", "user.name", _COMMITTER_NAME)
            await self._git("config", "user.email", _COMMITTER_EMAIL)
            rc, _, err = await self._git("config", "core.sshCommand", ssh_cmd)
            if rc != 0:
                raise GitError("git_config_failed", err)
            return await self._head()

    def _chown_tree_to_agent(self) -> None:
        """Recursively chown the freshly cloned tree to the agent uid (when root).

        The clone runs privileged (to read the root-only key), so its files land
        root-owned; the dropped agent must be able to read/write them."""
        for root, dirs, files in os.walk(self.workspace):
            base = os.path.basename(root)
            if base in self._RESERVED:
                dirs[:] = []
                continue
            sandbox.chown_to_agent(root)
            for f in files:
                sandbox.chown_to_agent(os.path.join(root, f))

    async def ls_remote(self, *, url: str, ssh_private_key: str) -> dict[str, Any]:
        """List remote branches over SSH. Returns {branches, default_branch}.
        Touches no local repo, so it runs entirely privileged (key is root-only)."""
        async with self._lock:
            key_path = None
            try:
                key_path, kh = self._write_key_material(ssh_private_key)
                env = self._ssh_env(url, key_path, kh)
                rc, out, err = await self._git(
                    "ls-remote", "--symref", url, "refs/heads/*", "HEAD",
                    env=env, timeout=VERIFY_TIMEOUT, privileged=True,
                )
            finally:
                if key_path:
                    try:
                        os.remove(key_path)
                    except OSError:
                        pass
            if rc != 0:
                raise GitError(classify_remote_error(err), redact(err, ssh_private_key))
            branches, default = parse_ls_remote_branches(out)
            return {"branches": branches, "default_branch": default}

    async def verify_remote(self, *, url: str, ssh_private_key: str) -> dict[str, Any]:
        """Reachability+auth check; returns branches so the UI can populate."""
        return await self.ls_remote(url=url, ssh_private_key=ssh_private_key)

    async def push(self, *, url: str, ssh_private_key: str, branch: str) -> str:
        """Push HEAD to <url> <branch> over SSH. ensure_repo runs as the agent
        uid (keeps .git agent-owned); the network push runs privileged so it can
        read the root-only key."""
        async with self._lock:
            await self._ensure_repo_locked()
            head = await self._head()
            key_path = None
            try:
                key_path, kh = self._write_key_material(ssh_private_key)
                env = self._ssh_env(url, key_path, kh)
                rc, _, err = await self._git(
                    "push", url, f"HEAD:refs/heads/{branch}",
                    env=env, timeout=PUSH_TIMEOUT, privileged=True,
                )
            finally:
                if key_path:
                    try:
                        os.remove(key_path)
                    except OSError:
                        pass
            if rc != 0:
                raise GitError(classify_remote_error(err), redact(err, ssh_private_key))
            return head

    async def log_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        async with self._lock:
            await self._ensure_repo_locked()
            rc, out, err = await self._git(
                "log", f"--max-count={limit}", "--shortstat",
                "--pretty=format:%x1e%H%x1f%ct%x1f%s",
            )
            if rc != 0:
                raise GitError("git_log_failed", err)
        entries: list[dict[str, Any]] = []
        for record in out.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            head_line, _, stat_tail = record.partition("\n")
            sha, _, rest = head_line.partition("\x1f")
            ts, _, subject = rest.partition("\x1f")
            task_match = _TASK_RE.match(subject)
            stat_match = _STAT_RE.search(stat_tail)
            entries.append({
                "sha": sha,
                "ts": int(ts),
                "message": subject,
                "task_id": task_match.group(1) if task_match else None,
                "files_changed": int(stat_match.group(1)) if stat_match else 0,
            })
        return entries

from __future__ import annotations

import pytest

from agentcore import sandbox


def test_build_child_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("SHIM_TOKEN", "supersecret")
    monkeypatch.setenv("CONTAINER_ID", "c1")
    monkeypatch.setenv("TENANT_ID", "t1")
    monkeypatch.setenv("SHIM_MAX_WORKERS", "4")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:8888")
    env = sandbox.build_child_env()
    assert "SHIM_TOKEN" not in env
    assert "CONTAINER_ID" not in env
    assert "TENANT_ID" not in env
    assert "SHIM_MAX_WORKERS" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["HTTPS_PROXY"] == "http://egress-proxy:8888"
    monkeypatch.setenv("EXA_API_KEY", "leaky")
    env = sandbox.build_child_env()
    assert "EXA_API_KEY" not in env


def test_build_child_env_forwards_all_proxy(monkeypatch):
    # ALL_PROXY must reach untrusted children: codex's MCP OAuth-discovery
    # reqwest client honors ALL_PROXY but ignores HTTP_PROXY/HTTPS_PROXY, so
    # without it every unauthenticated HTTP MCP server stalls startup ~40s on
    # proxy-bypassing well-known probes that fail DNS in the sandbox.
    monkeypatch.setenv("ALL_PROXY", "http://egress-proxy:8888")
    monkeypatch.setenv("all_proxy", "http://egress-proxy:8888")
    env = sandbox.build_child_env()
    assert env["ALL_PROXY"] == "http://egress-proxy:8888"
    assert env["all_proxy"] == "http://egress-proxy:8888"


def test_build_child_env_forwards_node_options(monkeypatch):
    # NODE_OPTIONS must reach untrusted children: the agent image sets it to
    # --require the node-proxy preload (EnvHttpProxyAgent), which makes Node's
    # built-in fetch honor the egress proxy. Stripped here, workspace *.mjs that
    # use fetch() fail with EAI_AGAIN even though curl (proxy-aware) works.
    monkeypatch.setenv("NODE_OPTIONS", "--require /opt/node-proxy/preload.cjs")
    env = sandbox.build_child_env()
    assert env["NODE_OPTIONS"] == "--require /opt/node-proxy/preload.cjs"


def test_build_child_env_sets_agent_home_by_default(monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    env = sandbox.build_child_env()
    assert env["HOME"] == sandbox.AGENT_HOME


def test_build_child_env_extra_overrides_home(monkeypatch):
    env = sandbox.build_child_env({"HOME": "/workspace/.agent-state/codex"})
    assert env["HOME"] == "/workspace/.agent-state/codex"


def test_drop_kwargs_empty_when_not_root(monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)
    assert sandbox.drop_kwargs() == {}


def test_drop_kwargs_drops_when_root(monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    kw = sandbox.drop_kwargs()
    assert kw == {"user": sandbox.AGENT_UID, "group": sandbox.AGENT_GID, "extra_groups": []}


def test_ensure_agent_dir_creates(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)  # non-root: skip chown
    target = tmp_path / "a" / "b"
    sandbox.ensure_agent_dir(str(target))
    assert target.is_dir()


@pytest.mark.asyncio
async def test_spawn_untrusted_runs_with_allowlisted_env(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)  # no drop under tests
    monkeypatch.setenv("SHIM_TOKEN", "secret")
    proc = await sandbox.spawn_untrusted(
        ["/bin/sh", "-c", "echo ${SHIM_TOKEN:-absent}"],
        cwd=str(tmp_path),
        env=sandbox.build_child_env(),
        stdout=__import__("asyncio").subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert out.decode().strip() == "absent"


def test_chown_to_agent_calls_chown_when_root(monkeypatch):
    calls = []
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    sandbox.chown_to_agent("/some/path")
    assert calls == [("/some/path", sandbox.AGENT_UID, sandbox.AGENT_GID)]


def test_ensure_agent_dir_chowns_when_root(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    target = tmp_path / "x" / "y"
    sandbox.ensure_agent_dir(str(target))
    assert target.is_dir()
    assert calls == [(str(target), sandbox.AGENT_UID, sandbox.AGENT_GID)]


def test_makedirs_agent_creates_tree_non_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)
    target = str(tmp_path / "a" / "b" / "c")
    sandbox.makedirs_agent(target)
    import os as _os
    assert _os.path.isdir(target)


def test_makedirs_agent_chowns_new_dirs_when_root(tmp_path, monkeypatch):
    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox.os, "chown", lambda p, u, g: calls.append((p, u, g)))
    parent = str(tmp_path / "a")
    target = str(tmp_path / "a" / "b")
    sandbox.makedirs_agent(target)
    chowned_paths = [c[0] for c in calls]
    assert parent in chowned_paths, "parent dir must be chowned to agent"
    assert target in chowned_paths, "leaf dir must be chowned to agent"
    for _, u, g in calls:
        assert u == sandbox.AGENT_UID
        assert g == sandbox.AGENT_GID


def test_makedirs_agent_empty_path_is_noop(monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    # must not raise
    sandbox.makedirs_agent("")


@pytest.mark.asyncio
async def test_spawn_untrusted_reads_lines_larger_than_64kib(tmp_path, monkeypatch):
    # Driver CLIs (codex/opencode) emit one JSON event per line; a single line
    # can embed large shell output. asyncio's default StreamReader limit is
    # 64 KiB, past which readline() raises ValueError. spawn_untrusted must raise
    # that ceiling so realistic agent output does not crash the read loop.
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)  # no drop under tests
    import asyncio as _asyncio
    big = 100_000  # > 64 KiB
    proc = await sandbox.spawn_untrusted(
        ["/bin/sh", "-c", f"head -c {big} /dev/zero | tr '\\0' 'a'; echo"],
        cwd=str(tmp_path),
        env=sandbox.build_child_env(),
        stdout=_asyncio.subprocess.PIPE,
    )
    line = await proc.stdout.readline()
    await proc.wait()
    assert len(line.rstrip(b"\n")) == big


def test_terminate_swallows_permission_error():
    # root without CAP_KILL signalling the agent-uid child returns EPERM; the
    # helper must swallow it so teardown never crashes / masks the real error.
    class Proc:
        def terminate(self):
            raise PermissionError(1, "Operation not permitted")

    sandbox.terminate(Proc())  # must not raise


def test_terminate_swallows_process_lookup_error():
    class Proc:
        def terminate(self):
            raise ProcessLookupError  # child already exited

    sandbox.terminate(Proc())  # must not raise


def test_terminate_calls_proc_terminate_when_alive():
    calls = []

    class Proc:
        def terminate(self):
            calls.append(True)

    sandbox.terminate(Proc())
    assert calls == [True]


@pytest.mark.asyncio
async def test_spawn_untrusted_tolerates_caller_kwargs(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 1000)  # drop_kwargs() == {}
    import asyncio as _asyncio
    proc = await sandbox.spawn_untrusted(
        ["/bin/sh", "-c", "exit 0"],
        cwd=str(tmp_path),
        env=sandbox.build_child_env(),
        stdout=_asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    assert proc.returncode == 0

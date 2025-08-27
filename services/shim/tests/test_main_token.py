from __future__ import annotations

import sys

from shim import main as shim_main


def test_main_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("SHIM_TOKEN", "env-token")
    captured = {}

    def fake_create_app(*, workspace, token, drivers, max_workers):
        captured["token"] = token
        return object()

    monkeypatch.setattr(shim_main, "create_app", fake_create_app)
    monkeypatch.setattr(shim_main.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(shim_main, "build_drivers", lambda: {})
    monkeypatch.setattr(shim_main.asyncio, "run", lambda *a, **k: None)

    class _StubGitOps:
        def __init__(self, *a, **k): ...
        def ensure_repo(self): ...

    monkeypatch.setattr(shim_main, "GitOps", _StubGitOps)
    monkeypatch.setattr(sys, "argv", ["shim", "--workspace", "/tmp/ws"])

    shim_main.main()
    assert captured["token"] == "env-token"


def test_main_runs_on_stdlib_asyncio_loop(monkeypatch):
    # The privilege-drop spawn (sandbox.drop_kwargs -> user/group/extra_groups)
    # only works on the stdlib asyncio loop; uvloop rejects those subprocess
    # kwargs with "unexpected kwargs", failing every untrusted task. uvicorn
    # defaults to uvloop when installed (uvicorn[standard]), so the shim must
    # explicitly pin loop="asyncio".
    captured: dict = {}
    monkeypatch.setattr(shim_main.uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr(shim_main, "create_app", lambda **k: object())
    monkeypatch.setattr(shim_main, "build_drivers", lambda: {})
    monkeypatch.setattr(shim_main.asyncio, "run", lambda *a, **k: None)

    class _StubGitOps:
        def __init__(self, *a, **k): ...
        def ensure_repo(self): ...

    monkeypatch.setattr(shim_main, "GitOps", _StubGitOps)
    monkeypatch.setattr(sys, "argv", ["shim", "--workspace", "/tmp/ws"])

    shim_main.main()
    assert captured.get("loop") == "asyncio"


def test_main_has_no_token_cli_flag(monkeypatch):
    # --token must no longer be accepted (prevents cmdline leakage).
    monkeypatch.setattr(sys, "argv", ["shim", "--token", "x"])
    monkeypatch.setattr(shim_main.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(shim_main, "create_app", lambda **k: object())
    monkeypatch.setattr(shim_main, "build_drivers", lambda: {})
    monkeypatch.setattr(shim_main.asyncio, "run", lambda *a, **k: None)
    try:
        shim_main.main()
        raised = False
    except SystemExit:
        raised = True
    assert raised  # argparse rejects the unknown --token flag

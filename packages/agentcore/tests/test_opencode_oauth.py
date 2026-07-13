import json
import os
import stat
from pathlib import Path

from agentcore import sandbox
from agentcore.drivers.opencode import build_env, provider_for_model, workspace_xdg, write_auth_json


def test_build_env_skips_api_key_for_oauth() -> None:
    env = build_env(
        {}, provider="openai", credential="acc-token",
        credential_kind="oauth_subscription",
    )
    assert "OPENAI_API_KEY" not in env


def test_build_env_sets_api_key_for_api_key_kind() -> None:
    env = build_env({}, provider="openai", credential="sk-key", credential_kind="api_key")
    assert env["OPENAI_API_KEY"] == "sk-key"


def test_write_auth_json_shape_and_perms(tmp_path) -> None:
    ws = str(tmp_path)
    # The driver creates the XDG dirs; mirror that here.
    for p in workspace_xdg(ws).values():
        Path(p).mkdir(parents=True, exist_ok=True)
    path = write_auth_json(
        ws,
        access_token="acc-1",
        refresh_token="ref-1",
        account_id="acct_9",
        expires_ms=1750000000000,
    )
    p = Path(path)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data == {
        "openai": {
            "type": "oauth",
            "access": "acc-1",
            "refresh": "ref-1",
            "accountId": "acct_9",
            "expires": 1750000000000,
        }
    }
    # The refresh token is included — opencode's Codex loader requires it to
    # register the credential and load the subscription model catalog (§13).
    assert data["openai"]["refresh"] == "ref-1"
    # 0600 perms.
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    # Path is under XDG_DATA_HOME/opencode/auth.json.
    assert path.endswith("/.agent-state/opencode/data/opencode/auth.json")


def test_write_auth_json_recreates_existing_file(tmp_path) -> None:
    """A 2nd+ oauth task on a persistent volume rewrites auth.json. The shim
    runs as root but the sandbox grants no CAP_FOWNER, so root cannot chmod a
    file a prior task already chowned to the agent uid (EPERM). write_auth_json
    must therefore RECREATE the file (fresh, root-owned before chmod) rather
    than truncate it in place. Holding the original inode open forces a recreate
    to allocate a new inode, so a different st_ino proves the file was replaced.
    """
    ws = str(tmp_path)
    for p in workspace_xdg(ws).values():
        Path(p).mkdir(parents=True, exist_ok=True)
    path = write_auth_json(ws, access_token="a1", refresh_token="r1",
                           account_id="x", expires_ms=1)
    with open(path) as held:  # pin the original inode so it can't be reused
        old_ino = os.fstat(held.fileno()).st_ino
        write_auth_json(ws, access_token="a2", refresh_token="r2",
                        account_id="x", expires_ms=2)
        new_ino = Path(path).stat().st_ino
    assert new_ino != old_ino, "auth.json was truncated in place, not recreated"
    assert json.loads(Path(path).read_text())["openai"]["access"] == "a2"
    assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600


def test_opencode_oauth_dir_chowned_when_root(tmp_path, monkeypatch) -> None:
    """When the shim runs as root, the oauth data dir is chowned to the agent
    so the dropped opencode process can write its sqlite db there."""
    calls: list[str] = []
    monkeypatch.setattr(sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox.os, "chown", lambda p, u, g: calls.append(str(p)))

    auth_path = write_auth_json(
        str(tmp_path),
        access_token="a",
        refresh_token="r",
        account_id="acc",
        expires_ms=0,
    )
    auth_dir = os.path.dirname(auth_path)
    sandbox.ensure_agent_dir(auth_dir)
    sandbox.chown_to_agent(auth_path)

    assert auth_dir in calls
    assert auth_path in calls


def test_build_env_sets_opencode_api_key_for_go_and_paid_zen() -> None:
    for model in ("opencode-go/glm-5.2", "opencode/kimi-k2"):
        env = build_env(
            {"PATH": "/usr/bin"},
            provider=provider_for_model(model),
            credential="oc-live-1234",
            credential_kind="api_key",
        )
        assert env["OPENCODE_API_KEY"] == "oc-live-1234"
        assert "ANTHROPIC_API_KEY" not in env


def test_build_env_keyless_free_zen_sets_no_var() -> None:
    env = build_env(
        {"PATH": "/usr/bin"},
        provider=provider_for_model("opencode/deepseek-v4-flash-free"),
        credential="",
        credential_kind="api_key",
    )
    assert "OPENCODE_API_KEY" not in env

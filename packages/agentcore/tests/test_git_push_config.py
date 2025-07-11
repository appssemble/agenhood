from __future__ import annotations

from agentcore.models import GitPushConfig


def test_git_push_config_uses_ssh_private_key():
    cfg = GitPushConfig(url="git@github.com:a/b.git", ssh_private_key="KEY", branch="main")
    assert cfg.ssh_private_key == "KEY"
    assert not hasattr(cfg, "token")

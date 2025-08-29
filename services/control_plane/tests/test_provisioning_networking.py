"""Assert the networking-relevant fields of agent provisioning (spec §4.7, §8.1).

This is the seam between Unit 2 (provisioning) and Unit 5 (networking): the
agent container MUST attach to only agent-runtime-internal and receive the
proxy + search env so the chokepoint works.
"""
from control_plane.config import Settings
from control_plane.docker_ctl import provision as provisioning  # Unit 2 module


def _settings(**over):
    base = dict(
        database_url="x", seed_tenant_id="t", seed_api_key="k", seed_llm_api_key="",
        agent_image_tag="v0.1.0", internal_network="agent-runtime-internal",
        readyz_timeout_seconds=1.0, shim_port=8080,
    )
    base.update(over)
    return Settings(**base)


def test_provisioning_uses_internal_network_and_proxy_env():
    # build_run_kwargs is the pure helper that assembles containers.run(**kwargs);
    # if Unit 2 inlines the dict, refactor that dict into this helper first.
    kwargs = provisioning.build_run_kwargs(
        settings=_settings(),
        image_tag="v0.1.0",
        docker_name="agent-c-01hx",
        cid="con_01hx",
        tenant_id="tnt_1",
        shim_token="shimtok",
        max_concurrent_tasks=4,
    )

    assert kwargs["network"] == "agent-runtime-internal"
    env = kwargs["environment"]
    assert env["HTTP_PROXY"] == "http://egress-proxy:8888"
    assert env["HTTPS_PROXY"] == "http://egress-proxy:8888"
    # ALL_PROXY is required so clients that only honor it (e.g. codex's MCP
    # OAuth-discovery reqwest client) still route through the egress proxy
    # instead of stalling ~40s on proxy-bypassing probes that fail DNS.
    assert env["ALL_PROXY"] == "http://egress-proxy:8888"
    assert env["SEARCH_PROVIDER_URL"] == "http://searxng:8080"
    assert "searxng" in env["NO_PROXY"]
    # The agent must NOT be given a direct egress network.
    assert "agent-runtime-egress" not in str(kwargs)


def test_build_run_kwargs_runs_as_root():
    from control_plane.docker_ctl.provision import build_run_kwargs

    kw = build_run_kwargs(
        settings=_settings(agent_image_tag="dev"),
        image_tag="dev",
        docker_name="agent-x",
        cid="c1",
        tenant_id="t1",
        shim_token="tok",
        max_concurrent_tasks=4,
    )
    assert kw["user"] == "0:0"
    # lockdown unchanged:
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kw["security_opt"]
    assert kw["read_only"] is True


def test_build_run_kwargs_grants_cap_kill_for_task_termination():
    # The driver runs as root and spawns the agent CLI dropped to uid 1000; to
    # SIGTERM that child on timeout/cancel root needs CAP_KILL, else kill()
    # across uids returns EPERM (see tsk_01kvsjy…). Hardening otherwise intact.
    from control_plane.docker_ctl.provision import build_run_kwargs

    kw = build_run_kwargs(
        settings=_settings(agent_image_tag="dev"),
        image_tag="dev",
        docker_name="agent-x",
        cid="c1",
        tenant_id="t1",
        shim_token="tok",
        max_concurrent_tasks=4,
    )
    assert "KILL" in kw["cap_add"]
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kw["security_opt"]

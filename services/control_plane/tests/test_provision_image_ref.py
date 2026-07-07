from control_plane.config import Settings
from control_plane.docker_ctl.provision import build_run_kwargs


def _settings(**over):
    base = dict(
        database_url="x", seed_tenant_id="t", seed_api_key="k", seed_llm_api_key="",
        agent_image_tag="v0.3.0", internal_network="agent-runtime-internal",
        readyz_timeout_seconds=1.0, shim_port=8080,
    )
    base.update(over)
    return Settings(**base)


def test_image_ref_local_when_no_registry():
    s = _settings(agent_registry="")
    kw = build_run_kwargs(
        settings=s, docker_name="agent-x", cid="c1", tenant_id="t1",
        shim_token="tok", max_concurrent_tasks=4, image_tag="v0.3.0",
        mem_limit="4g", cpus=2.0,
    )
    assert kw["image"] == "agent-runtime:v0.3.0"


def test_image_ref_uses_registry_prefix():
    s = _settings(agent_registry="registry.example.com")
    kw = build_run_kwargs(
        settings=s, docker_name="agent-x", cid="c1", tenant_id="t1",
        shim_token="tok", max_concurrent_tasks=4, image_tag="v0.3.0",
        mem_limit="4g", cpus=2.0,
    )
    assert kw["image"] == "registry.example.com/agent-runtime:v0.3.0"


def test_image_tag_is_per_container_not_settings_default():
    # The registry is global (env), but the TAG must come from the per-container
    # resolved value (create-request override / stored DB tag on recreate), NOT
    # settings.agent_image_tag.
    s = _settings(agent_registry="registry.example.com", agent_image_tag="v0.3.0")
    kw = build_run_kwargs(
        settings=s, docker_name="agent-x", cid="c1", tenant_id="t1",
        shim_token="tok", max_concurrent_tasks=4, image_tag="v0.2.0",
        mem_limit="4g", cpus=2.0,
    )
    assert kw["image"] == "registry.example.com/agent-runtime:v0.2.0"


def test_resources_come_from_explicit_params_not_settings():
    # mem_limit/cpus are now resolved by the caller (resolve_resource_limits)
    # and passed in explicitly — build_run_kwargs no longer reads them off
    # settings. pids_limit is still settings-derived (it isn't per-container).
    s = _settings(agent_pids_limit=256)
    kw = build_run_kwargs(
        settings=s, docker_name="agent-x", cid="c1", tenant_id="t1",
        shim_token="tok", max_concurrent_tasks=4, image_tag="v0.3.0",
        mem_limit="2g", cpus=1.0,
    )
    assert kw["mem_limit"] == "2g"
    assert kw["memswap_limit"] == "2g"
    assert kw["nano_cpus"] == 1_000_000_000
    assert kw["pids_limit"] == 256

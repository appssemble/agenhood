from control_plane.config import Settings


def test_agent_resource_defaults(monkeypatch):
    for k in ("AGENT_REGISTRY", "AGENT_MEM_LIMIT", "AGENT_MEMSWAP_LIMIT",
              "AGENT_CPUS", "AGENT_PIDS_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.agent_registry == ""
    assert s.agent_mem_limit == "4g"
    assert s.agent_memswap_limit == "4g"
    assert s.agent_cpus == 2.0
    assert s.agent_pids_limit == 512


def test_agent_resource_overrides(monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY", "registry.example.com")
    monkeypatch.setenv("AGENT_MEM_LIMIT", "2g")
    monkeypatch.setenv("AGENT_CPUS", "1")
    monkeypatch.setenv("AGENT_PIDS_LIMIT", "256")
    s = Settings.from_env()
    assert s.agent_registry == "registry.example.com"
    assert s.agent_mem_limit == "2g"
    # memswap defaults to mem_limit when unset
    assert s.agent_memswap_limit == "2g"
    assert s.agent_cpus == 1.0
    assert s.agent_pids_limit == 256

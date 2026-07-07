from control_plane.config import Settings


def test_agent_resource_defaults(monkeypatch):
    for k in (
        "AGENT_REGISTRY", "AGENT_MEM_LIMIT_FULL", "AGENT_CPUS_FULL",
        "AGENT_MEM_LIMIT_SLIM", "AGENT_CPUS_SLIM", "AGENT_MEM_LIMIT_MIN",
        "AGENT_MEM_LIMIT_MAX", "AGENT_CPUS_MIN", "AGENT_CPUS_MAX",
        "AGENT_PIDS_LIMIT",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.agent_registry == ""
    assert s.agent_mem_limit_full == "4g"
    assert s.agent_cpus_full == 2.0
    assert s.agent_mem_limit_slim == "2g"
    assert s.agent_cpus_slim == 1.0
    assert s.agent_mem_limit_min == "256m"
    assert s.agent_mem_limit_max == "8g"
    assert s.agent_cpus_min == 0.25
    assert s.agent_cpus_max == 4.0
    assert s.agent_pids_limit == 512


def test_agent_resource_overrides(monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY", "registry.example.com")
    monkeypatch.setenv("AGENT_MEM_LIMIT_FULL", "6g")
    monkeypatch.setenv("AGENT_CPUS_FULL", "3")
    monkeypatch.setenv("AGENT_MEM_LIMIT_SLIM", "1g")
    monkeypatch.setenv("AGENT_CPUS_SLIM", "0.5")
    monkeypatch.setenv("AGENT_MEM_LIMIT_MIN", "128m")
    monkeypatch.setenv("AGENT_MEM_LIMIT_MAX", "16g")
    monkeypatch.setenv("AGENT_CPUS_MIN", "0.1")
    monkeypatch.setenv("AGENT_CPUS_MAX", "8")
    monkeypatch.setenv("AGENT_PIDS_LIMIT", "256")
    s = Settings.from_env()
    assert s.agent_registry == "registry.example.com"
    assert s.agent_mem_limit_full == "6g"
    assert s.agent_cpus_full == 3.0
    assert s.agent_mem_limit_slim == "1g"
    assert s.agent_cpus_slim == 0.5
    assert s.agent_mem_limit_min == "128m"
    assert s.agent_mem_limit_max == "16g"
    assert s.agent_cpus_min == 0.1
    assert s.agent_cpus_max == 8.0
    assert s.agent_pids_limit == 256

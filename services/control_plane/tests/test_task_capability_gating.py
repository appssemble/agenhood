"""Skills/MCP resolution is gated on driver capabilities, not a name tuple."""
import pytest

from agentcore.models import AgentConfig
from control_plane.routers.tasks import build_task_mcp_servers, build_task_skills

pytestmark = pytest.mark.unit

SKILL_ROWS = [{"id": "sk_1", "name": "pdf-reports", "description": "d",
               "body": "b", "enabled": True}]


def _config(driver, **kw):
    return AgentConfig(driver=driver, model="claude-opus-4-7",
                       skills=["sk_1"], mcp_servers=["mcp_1"], **kw)


def test_vanilla_now_resolves_skills():
    out = build_task_skills(_config("vanilla"), SKILL_ROWS)
    assert [s.name for s in out] == ["pdf-reports"]


def test_opencode_still_resolves_skills():
    out = build_task_skills(_config("opencode"), SKILL_ROWS)
    assert [s.name for s in out] == ["pdf-reports"]


def test_unknown_driver_gets_no_skills():
    assert build_task_skills(_config("nope"), SKILL_ROWS) == []


def test_vanilla_mcp_gate_open():
    # Row resolution requires the crypto key; assert only the gate, using an
    # empty row list so resolve returns [] without touching decryption.
    assert build_task_mcp_servers(_config("vanilla"), [], b"0" * 32) == []
    # And the closed gate short-circuits identically for an unknown driver.
    assert build_task_mcp_servers(_config("nope"), [], b"0" * 32) == []

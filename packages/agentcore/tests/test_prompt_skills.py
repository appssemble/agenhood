import pytest

from agentcore.models import AgentConfig, ResolvedLimits, ShimSkill, TaskBody
from agentcore.prompt import assemble_system_prompt

pytestmark = pytest.mark.unit

LIMITS = ResolvedLimits(max_iterations=10, max_tokens=1000, timeout_seconds=60)


def _prompt(skills):
    return assemble_system_prompt(
        config=AgentConfig(driver="vanilla", model="m"),
        driver_default_system_prompt="base",
        tool_specs=[],
        task=TaskBody(prompt="x"),
        limits=LIMITS,
        skills=skills,
    )


def test_no_skills_no_section():
    assert "## Skills" not in _prompt(None)
    assert "## Skills" not in _prompt([])


def test_skills_section_lists_names_and_descriptions_only():
    out = _prompt([
        ShimSkill(name="pdf-reports", description="Branded PDF reports", body="SECRET-BODY"),
        ShimSkill(name="crm-sync", description="Sync contacts", body="ALSO-SECRET"),
    ])
    assert "## Skills" in out
    assert "- pdf-reports: Branded PDF reports" in out
    assert "- crm-sync: Sync contacts" in out
    assert "skill` tool" in out  # instructs lazy loading
    assert "/workspace/.agent-runtime/skills/" in out
    assert "SECRET-BODY" not in out and "ALSO-SECRET" not in out  # progressive disclosure

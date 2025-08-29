"""Discovery-path gate: write_skills lands a SKILL.md where the real codex
binary discovers it (codex's $HOME/.agents/skills, under the redirected
codex_home), verified inside the agent image. Mirrors
integration/test_opencode_skills.py for image tag + skip."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

pytestmark = pytest.mark.integration

_SCRIPT = """\
import asyncio, json
from pathlib import Path

import agentcore.drivers.codex as cx
from agentcore.drivers.skills_md import write_skills
from agentcore.models import ShimSkill

ws = "/workspace"
Path(ws, ".agent-runtime").mkdir(parents=True, exist_ok=True)

async def main():
    names = await write_skills(cx.skills_dir(ws), [
        ShimSkill(name="probe-skill", description='A probe: "quote" + colon',
                  body="# Probe\\nDo the probe."),
    ])
    md_path = Path(cx.skills_dir(ws)) / "probe-skill" / "SKILL.md"
    md = md_path.read_text() if md_path.exists() else ""
    import shutil as _sh
    print(json.dumps({
        "names": names,
        "exists": md_path.exists(),
        "name_line": "name: probe-skill" in md,
        "desc_escaped": 'description: "A probe: \\\\"quote\\\\" + colon"' in md,
        "under_codex_home": str(md_path).startswith(cx.codex_home(ws)),
        "agents_path": "/.agents/skills/" in str(md_path),
        "codex_present": _sh.which("codex") is not None,
    }))

asyncio.run(main())
"""


async def test_write_skills_lands_at_codex_discovery_path_in_image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    tag = await asyncio.create_subprocess_exec(
        "docker", "tag", "agent-runtime:latest", "agent-runtime:codex-skills-it",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, tag_err = await tag.communicate()
    if tag.returncode != 0:
        pytest.skip(f"agent image not available: {tag_err.decode()[-300:]}")

    run = await asyncio.create_subprocess_exec(
        "docker", "run", "--rm", "-i",
        "--entrypoint", "/opt/venv/bin/python",
        "agent-runtime:codex-skills-it", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            run.communicate(input=_SCRIPT.encode()), timeout=60
        )
    except TimeoutError:
        run.kill()
        pytest.fail("codex skills materialization script timed out in container")

    assert run.returncode == 0, f"stderr={err.decode()[-2000:]}\nstdout={out.decode()[-500:]}"
    result = json.loads(out.decode().strip().splitlines()[-1])

    assert result["names"] == ["probe-skill"]
    assert result["exists"], "SKILL.md not written in the real image"
    assert result["name_line"], "frontmatter name missing"
    assert result["desc_escaped"], "description not YAML-escaped as expected"
    assert result["under_codex_home"], "SKILL.md is not under codex_home"
    assert result["agents_path"], "SKILL.md is not under .agents/skills"
    assert result["codex_present"], "codex binary missing from the agent image"

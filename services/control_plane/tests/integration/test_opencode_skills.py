"""Discovery-path gate: materialize_skills lands a SKILL.md where the real
opencode binary discovers it (global XDG skills path), verified inside the
agent image. Mirrors integration/test_opencode_driver.py for image tag + skip.

If a future opencode version stops reading the global path, the documented
fallback (spec) is to also write the project <workspace>/.opencode/skills path
and exclude .opencode from the shim file listing."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

pytestmark = pytest.mark.integration

# Runs inside the container: materialize a probe skill, then assert the file
# exists at opencode's global discovery path with the right frontmatter, and
# report whether the opencode binary is present.
_SCRIPT = """\
import asyncio, json, os
from pathlib import Path

import agentcore.drivers.opencode as oc
from agentcore.models import ShimSkill

ws = "/workspace"
Path(ws, ".agent-runtime").mkdir(parents=True, exist_ok=True)

async def main():
    names = await oc.materialize_skills(ws, [
        ShimSkill(name="probe-skill", description='A probe: "quote" + colon',
                  body="# Probe\\nDo the probe."),
    ])
    md_path = Path(oc.skills_dir(ws)) / "probe-skill" / "SKILL.md"
    md = md_path.read_text() if md_path.exists() else ""
    import shutil as _sh
    print(json.dumps({
        "names": names,
        "exists": md_path.exists(),
        "name_line": "name: probe-skill" in md,
        "desc_escaped": 'description: "A probe: \\\\"quote\\\\" + colon"' in md,
        "global_path": str(md_path).startswith(oc.workspace_xdg(ws)["XDG_CONFIG_HOME"]),
        "opencode_present": _sh.which("opencode") is not None,
    }))

asyncio.run(main())
"""


async def test_materialize_lands_at_opencode_discovery_path_in_image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    tag = await asyncio.create_subprocess_exec(
        "docker", "tag", "agent-runtime:latest", "agent-runtime:skills-it",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, tag_err = await tag.communicate()
    if tag.returncode != 0:
        pytest.skip(f"agent image not available: {tag_err.decode()[-300:]}")

    run = await asyncio.create_subprocess_exec(
        "docker", "run", "--rm", "-i",
        "--entrypoint", "/opt/venv/bin/python",
        "agent-runtime:skills-it", "-",
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
        pytest.fail("skills materialization script timed out in container")

    assert run.returncode == 0, f"stderr={err.decode()[-2000:]}\nstdout={out.decode()[-500:]}"
    result = json.loads(out.decode().strip().splitlines()[-1])

    assert result["names"] == ["probe-skill"]
    assert result["exists"], "SKILL.md not written in the real image"
    assert result["name_line"], "frontmatter name missing"
    assert result["desc_escaped"], "description not YAML-escaped as expected"
    assert result["global_path"], "SKILL.md is not under opencode's global XDG skills path"
    # The discovery path only matters if the binary that reads it is actually
    # in the image. opencode's install is best-effort in the Dockerfile, so a
    # dropped binary is exactly when skills would silently go undiscovered —
    # fail the gate loudly rather than pass on a path nothing reads.
    assert result["opencode_present"], "opencode binary missing from the agent image"

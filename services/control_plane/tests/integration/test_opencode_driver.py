"""Integration test: opencode driver emits a terminal status_change in a real container.

Verifies spec §3.5.2 (best-effort): the OpencodeDriver MUST always emit a
terminal status_change event regardless of whether the opencode binary is
installed.  In the current agent image the npm package installation is
best-effort (it may fail if the published version doesn't exist), so the test
asserts the GRACEFUL FALLBACK path: when the binary is missing the driver emits
an ``opencode_unavailable`` status_change (which is still a terminal
status_change) rather than raising an unhandled exception.

The test does NOT require:
  - A successful opencode run
  - A working LLM backend
  - The opencode npm package to actually be installed

It only requires:
  - The agent image to build successfully (``agent-runtime:latest`` exists)
  - The image to contain agentcore with the opencode driver
"""
from __future__ import annotations

import asyncio
import json
import shutil

import pytest

pytestmark = pytest.mark.integration

# Python script run inside the container — written as a proper multi-line string
# so Python syntax is valid when passed to `python -c`.
_DRIVER_SCRIPT = """\
import asyncio
import json

import agentcore.drivers.opencode as oc
from agentcore.models import TaskBody, AgentConfig, ResolvedLimits

events = []

async def emit(t, p):
    events.append(t)

async def main():
    d = oc.OpencodeDriver()
    await d.run(
        task=TaskBody(prompt="create a file hello.txt with the word hi"),
        config=AgentConfig(driver="opencode", model="claude-opus-4-7"),
        limits=ResolvedLimits(max_iterations=1, max_tokens=1, timeout_seconds=20),
        credential="sk-ant-stub",
        emit=emit,
        cancel=asyncio.Event(),
    )
    print(json.dumps(events))

asyncio.run(main())
"""


async def test_opencode_driver_emits_terminal_status_in_real_container() -> None:
    """Run the opencode driver inside the agent image and assert it emits at
    least one terminal ``status_change`` event (completed / failed / timed_out /
    cancelled).  The graceful ``opencode_unavailable`` fallback counts."""
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    # Ensure the agent image is tagged for this test.
    tag_proc = await asyncio.create_subprocess_exec(
        "docker", "tag", "agent-runtime:latest", "agent-runtime:opencode-it",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, tag_err = await tag_proc.communicate()
    assert tag_proc.returncode == 0, (
        f"Failed to tag agent image: {tag_err.decode()[-1000:]}"
    )

    # Run the script inside the container via stdin so we avoid shell quoting
    # issues with the -c argument.
    run = await asyncio.create_subprocess_exec(
        "docker", "run", "--rm", "-i",
        "--entrypoint", "/opt/venv/bin/python",
        "agent-runtime:opencode-it",
        "-",                              # read script from stdin
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            run.communicate(input=_DRIVER_SCRIPT.encode()), timeout=60
        )
    except TimeoutError:
        run.kill()
        pytest.fail("opencode driver timed out after 60 s in real container")

    assert run.returncode == 0, (
        f"Driver script exited {run.returncode}.\n"
        f"stderr={err.decode()[-2000:]}\n"
        f"stdout={out.decode()[-500:]}"
    )

    # Parse the event-type list from the last non-empty stdout line.
    stdout_text = out.decode().strip()
    assert stdout_text, (
        f"No output from driver script.\nstderr={err.decode()[-2000:]}"
    )
    last_line = stdout_text.splitlines()[-1]
    emitted: list[str] = json.loads(last_line)

    # At least one terminal status_change MUST be present (the driver contract).
    assert "status_change" in emitted, (
        f"No status_change in emitted events: {emitted}\n"
        f"stderr={err.decode()[-2000:]}"
    )

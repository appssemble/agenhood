"""Integration tests for image variant build + control-plane gate (spec §9.1/§9.2/§9.3)."""
import os
import shutil
import subprocess

import pytest

DOCKER = shutil.which("docker") is not None and (
    bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")
)


@pytest.mark.unit
def test_gate_refuses_rendered_web_fetch_on_slim():
    """Pure gate assertion — always runs. A config enabling rendered web_fetch (chromium) is
    refused on a slim container."""
    from dataclasses import dataclass

    from control_plane import variants
    from control_plane.errors import Conflict

    @dataclass(frozen=True)
    class Spec:
        name: str
        requires_image_feature: str | None = None

    @dataclass(frozen=True)
    class Tool:
        spec: Spec

    @dataclass(frozen=True)
    class Caps:
        requires_image_feature: str | None = None

    @dataclass(frozen=True)
    class Driver:
        name: str
        capabilities: Caps

    drivers = {"vanilla": Driver("vanilla", Caps())}
    tools = {"web_fetch": Tool(Spec("web_fetch", requires_image_feature="chromium"))}
    with pytest.raises(Conflict) as ei:
        variants.assert_config_runnable_on_variant(
            variant="slim",
            driver_name="vanilla",
            tool_names=["web_fetch"],
            drivers=drivers,
            tools=tools,
        )
    assert "chromium" in ei.value.message and "slim" in ei.value.message


@pytest.mark.integration
@pytest.mark.skipif(not DOCKER, reason="needs docker daemon to build the slim image")
def test_slim_image_has_no_chromium():
    """Build the slim variant and confirm Chromium is absent (spec Phase 4 test)."""
    subprocess.run(["make", "image-slim"], check=True, cwd=_repo_root())
    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            "agent-runtime:v0.1.0-slim",
            "-c",
            "command -v chromium || echo NO_CHROMIUM",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NO_CHROMIUM" in out.stdout


def _repo_root():
    import pathlib

    p = pathlib.Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "Makefile").exists() and (parent / "images").exists():
            return str(parent)
    raise RuntimeError("repo root not found")

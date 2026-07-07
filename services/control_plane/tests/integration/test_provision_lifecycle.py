from __future__ import annotations

import subprocess

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration]


def _docker_exists(kind: str, name: str) -> bool:
    """Return True if the named Docker container or volume exists."""
    if kind == "container":
        out = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        ).stdout
        return name in out.splitlines()
    out = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    ).stdout
    return name in out.splitlines()


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_create_then_delete_lifecycle(seeded_app: object) -> None:
    headers = {"Authorization": "Bearer tk_live_seedkey"}
    async with await _client(seeded_app) as c:
        r = await c.post(
            "/v1/containers",
            headers=headers,
            json={
                "name": "lc1",
                "config": {
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "tools": ["read_file", "write_file"],
                },
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["status"] == "running"

        docker_name = "agent-c-" + cid[len("con_"):]
        volume_name = "agent-vol-" + cid
        assert _docker_exists("container", docker_name), (
            f"Expected Docker container {docker_name!r} to exist"
        )
        assert _docker_exists("volume", volume_name), (
            f"Expected Docker volume {volume_name!r} to exist"
        )

        # DELETE permanently purges the container, the volume, and the row.
        d = await c.request("DELETE", f"/v1/containers/{cid}", headers=headers)
        assert d.status_code == 200, d.text
        assert d.json()["status"] == "deleted"
        assert not _docker_exists("container", docker_name), (
            f"Expected Docker container {docker_name!r} to be removed"
        )
        assert not _docker_exists("volume", volume_name), (
            f"Expected Docker volume {volume_name!r} to be removed"
        )
        g = await c.get(f"/v1/containers/{cid}", headers=headers)
        assert g.status_code == 404


async def test_update_resources_live_no_restart(seeded_app: object) -> None:
    headers = {"Authorization": "Bearer tk_live_seedkey"}
    async with await _client(seeded_app) as c:
        r = await c.post(
            "/v1/containers",
            headers=headers,
            json={
                "name": "res1",
                "config": {"driver": "vanilla", "model": "claude-opus-4-7", "tools": []},
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["mem_limit"] == "4g"
        assert r.json()["cpus"] == 2.0
        docker_name = "agent-c-" + cid[len("con_"):]

        p = await c.patch(
            f"/v1/containers/{cid}/resources",
            headers=headers,
            json={"mem_limit": "1g", "cpus": 0.5},
        )
        assert p.status_code == 200, p.text
        assert p.json() == {
            "id": cid, "status": "running", "mem_limit": "1g", "cpus": 0.5, "applied": True,
        }

        inspect = subprocess.run(
            [
                "docker", "inspect", docker_name, "--format",
                "{{.HostConfig.Memory}} {{.HostConfig.CpuPeriod}} {{.HostConfig.CpuQuota}}",
            ],
            capture_output=True, text=True,
        ).stdout.strip()
        mem_bytes, cpu_period, cpu_quota = inspect.split()
        assert int(mem_bytes) == 1 * 1024**3
        assert int(cpu_period) == 100_000
        assert int(cpu_quota) == 50_000

        d = await c.request("DELETE", f"/v1/containers/{cid}", headers=headers)
        assert d.status_code == 200, d.text

from __future__ import annotations

import subprocess

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from control_plane.db import make_engine, make_session_factory

pytestmark = [pytest.mark.integration]

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}


def _docker_exists(kind: str, name: str) -> bool:
    cmd = (
        ["docker", "ps", "-a", "--format", "{{.Names}}"]
        if kind == "container"
        else ["docker", "volume", "ls", "--format", "{{.Name}}"]
    )
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return name in out.splitlines()


def _docker_volume_rm(name: str) -> None:
    subprocess.run(
        ["docker", "volume", "rm", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def _create(c: AsyncClient, name: str) -> str:
    r = await c.post(
        "/v1/containers",
        headers=_HEADERS,
        json={
            "name": name,
            "config": {"driver": "vanilla", "model": "claude-opus-4-7",
                       "tools": ["read_file", "write_file"]},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _restore_audit_count(app_settings: object, cid: str) -> int:
    engine = make_engine(app_settings)  # type: ignore[arg-type]
    try:
        factory = make_session_factory(engine)
        async with factory() as s:
            return (await s.execute(
                text("SELECT count(*) FROM audit_log "
                     "WHERE target_id = :cid AND action = 'container.restore'"),
                {"cid": cid},
            )).scalar() or 0
    finally:
        await engine.dispose()


async def test_destroy_removes_container_keeps_volume_and_row(seeded_app: object) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "destroy-keepvol")
        docker_name = "agent-c-" + cid[len("con_"):]
        volume_name = "agent-vol-" + cid
        try:
            d = await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            assert d.status_code == 200, d.text
            assert d.json()["status"] == "archived"
            assert not _docker_exists("container", docker_name)
            assert _docker_exists("volume", volume_name)
            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.status_code == 200
            assert g.json()["status"] == "archived"
        finally:
            _docker_volume_rm(volume_name)


async def test_destroy_is_idempotent(seeded_app: object) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "destroy-idem")
        volume_name = "agent-vol-" + cid
        try:
            d1 = await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            assert d1.status_code == 200, d1.text
            assert d1.json()["status"] == "archived"
            # Second destroy is a no-op and still reports the real (archived) status.
            d2 = await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            assert d2.status_code == 200, d2.text
            assert d2.json()["status"] == "archived"
        finally:
            _docker_volume_rm(volume_name)


async def test_restore_brings_destroyed_container_back(
    seeded_app: object, app_settings: object
) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "restore-explicit")
        docker_name = "agent-c-" + cid[len("con_"):]
        volume_name = "agent-vol-" + cid
        try:
            await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            assert not _docker_exists("container", docker_name)

            r = await c.post(f"/v1/containers/{cid}/restore", headers=_HEADERS)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "running"
            assert _docker_exists("container", docker_name)
            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.json()["status"] == "running"
            assert await _restore_audit_count(app_settings, cid) == 1
        finally:
            await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            _docker_volume_rm(volume_name)


async def test_restore_on_running_is_idempotent(
    seeded_app: object, app_settings: object
) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "restore-idem")
        volume_name = "agent-vol-" + cid
        try:
            r = await c.post(f"/v1/containers/{cid}/restore", headers=_HEADERS)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "running"
            # No-op restore on a running container must not write an audit row.
            assert await _restore_audit_count(app_settings, cid) == 0
        finally:
            await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            _docker_volume_rm(volume_name)


async def test_delete_purges_container_volume_and_row(
    seeded_app: object, app_settings: object
) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "hard-delete")
        docker_name = "agent-c-" + cid[len("con_"):]
        volume_name = "agent-vol-" + cid

        d = await c.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
        assert d.status_code == 200, d.text
        assert d.json()["status"] == "deleted"

        assert not _docker_exists("container", docker_name)
        assert not _docker_exists("volume", volume_name)

        g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
        assert g.status_code == 404

        engine = make_engine(app_settings)  # type: ignore[arg-type]
        try:
            factory = make_session_factory(engine)
            async with factory() as s:
                row = (await s.execute(
                    text("SELECT id FROM containers WHERE id = :cid"), {"cid": cid}
                )).first()
                assert row is None
                tasks = (await s.execute(
                    text("SELECT count(*) FROM tasks WHERE container_id = :cid"),
                    {"cid": cid},
                )).scalar()
                assert tasks == 0
                audit = (await s.execute(
                    text("SELECT count(*) FROM audit_log WHERE target_id = :cid "
                         "AND action = 'container.delete'"),
                    {"cid": cid},
                )).scalar()
                assert audit == 1
        finally:
            await engine.dispose()


async def test_delete_missing_returns_404(seeded_app: object) -> None:
    async with await _client(seeded_app) as c:
        cid = await _create(c, "delete-twice")
        await c.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
        again = await c.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
        assert again.status_code == 404


async def test_delete_purges_task_and_event_rows(
    seeded_app: object, app_settings: object
) -> None:
    """DELETE must purge the container's tasks (FK RESTRICT requires tasks-first)
    and cascade to events, before removing the container row."""
    async with await _client(seeded_app) as c:
        cid = await _create(c, "delete-with-tasks")
        volume_name = "agent-vol-" + cid
        task_id = "tsk_deltest1"
        engine = make_engine(app_settings)  # type: ignore[arg-type]
        try:
            factory = make_session_factory(engine)
            # Seed a task + event row referencing the container.
            async with factory() as s:
                await s.execute(
                    text(
                        "INSERT INTO tasks (id, tenant_id, container_id, driver, body, "
                        "config_snapshot, status) VALUES (:tid, :ten, :cid, 'vanilla', "
                        "'{}'::jsonb, '{}'::jsonb, 'completed')"
                    ),
                    {"tid": task_id, "ten": app_settings.seed_tenant_id, "cid": cid},
                )
                await s.execute(
                    text(
                        "INSERT INTO events (task_id, seq, type, payload) "
                        "VALUES (:tid, 1, 'log', '{}'::jsonb)"
                    ),
                    {"tid": task_id},
                )
                await s.commit()

            d = await c.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
            assert d.status_code == 200, d.text

            async with factory() as s:
                tasks = (await s.execute(
                    text("SELECT count(*) FROM tasks WHERE container_id = :cid"),
                    {"cid": cid},
                )).scalar()
                events = (await s.execute(
                    text("SELECT count(*) FROM events WHERE task_id = :tid"),
                    {"tid": task_id},
                )).scalar()
                assert tasks == 0, "tasks must be purged"
                assert events == 0, "events must cascade-delete with their task"
        finally:
            await engine.dispose()
            _docker_volume_rm(volume_name)


async def test_delete_from_archived_removes_retained_volume(seeded_app: object) -> None:
    """Delete works from the archived (destroyed) state: no live container, but the
    retained volume + row must still be removed (NotFound-safe stop/rm)."""
    async with await _client(seeded_app) as c:
        cid = await _create(c, "delete-archived")
        docker_name = "agent-c-" + cid[len("con_"):]
        volume_name = "agent-vol-" + cid
        try:
            await c.post(f"/v1/containers/{cid}/destroy", headers=_HEADERS)
            assert not _docker_exists("container", docker_name)
            assert _docker_exists("volume", volume_name)

            d = await c.request("DELETE", f"/v1/containers/{cid}", headers=_HEADERS)
            assert d.status_code == 200, d.text
            assert d.json()["status"] == "deleted"
            assert not _docker_exists("volume", volume_name)
            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.status_code == 404
        finally:
            _docker_volume_rm(volume_name)

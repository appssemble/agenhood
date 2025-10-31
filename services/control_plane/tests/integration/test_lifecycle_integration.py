"""End-to-end lifecycle integration tests (real Docker + real Postgres, stub LLM).

Covers:
- pause(force) cancels an in-flight task; plain pause on a busy container is 409.
- archive then submit: rehydrates from the retained volume with workspace intact.
- reconciler: docker kill a running container, reconcile, next task resumes.
- recover: force container into error, recover, same volume, file survives.
- admission/LRU: max_running_containers=1 — idle LRU-paused so second can run;
  if the only running container is busy, 503 running_capacity_exhausted.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

DOCKER = shutil.which("docker") is not None and (
    bool(os.environ.get("DOCKER_HOST")) or os.path.exists("/var/run/docker.sock")
)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DOCKER, reason="lifecycle integration needs a docker daemon"),
]

# ---------------------------------------------------------------------------
# Shared headers (seed API key) and client helper
# ---------------------------------------------------------------------------

_HEADERS = {"Authorization": "Bearer tk_live_seedkey"}
_ADMIN_HEADERS = {"Authorization": "Bearer boot-test-key"}


async def _client(app: object) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# Docker helpers (verify invariants without going through the API)
# ---------------------------------------------------------------------------


def _docker_container_exists(name: str) -> bool:
    out = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout
    return name in out.splitlines()


def _docker_volume_exists(name: str) -> bool:
    out = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    ).stdout
    return name in out.splitlines()


def _docker_kill(docker_name: str) -> None:
    """Hard-kill a container (SIGKILL; exit code 137)."""
    subprocess.run(
        ["docker", "kill", docker_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _docker_rm(docker_name: str) -> None:
    """Force-remove a container without touching the volume."""
    subprocess.run(
        ["docker", "rm", "-f", docker_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _docker_name(cid: str) -> str:
    """Derive the Docker container name from the control-plane container id."""
    from control_plane.ids import docker_name_for

    return docker_name_for(cid)


def _volume_name(cid: str) -> str:
    """Derive the Docker volume name from the control-plane container id."""
    from control_plane.ids import volume_name_for

    return volume_name_for(cid)


# ---------------------------------------------------------------------------
# Lifecycle helper fixtures injected into tests via parameters
# ---------------------------------------------------------------------------

async def _archive_via_lifecycle(app: object, cid: str) -> None:
    """Run lifecycle.archive against the app's session_factory + docker_client.

    This is what the dormant sweep does; we call it directly to avoid
    sleeping for archive_after_hours.
    """
    from control_plane import lifecycle

    session_factory = app.state.session_factory  # type: ignore[attr-defined]
    docker_client = app.state.docker_client  # type: ignore[attr-defined]
    async with session_factory() as db:
        await lifecycle.archive(db, docker_client, cid)
        await db.commit()


async def _reconcile_via_app(app: object) -> None:
    """Run reconcile_all against the app's session_factory + docker_client."""
    from control_plane.reconciler import reconcile_all

    session_factory = app.state.session_factory  # type: ignore[attr-defined]
    docker_client = app.state.docker_client  # type: ignore[attr-defined]
    shim = app.state.shim  # type: ignore[attr-defined]
    async with session_factory() as db:
        await reconcile_all(db, docker_client, shim)
        await db.commit()


async def _force_error_via_db(app: object, cid: str) -> None:
    """Set a container to status='error' in the DB and remove its Docker container.

    Leaves the volume intact so recover can re-provision from it.
    Simulates a provisioning-interrupted error.
    """
    session_factory = app.state.session_factory  # type: ignore[attr-defined]
    async with session_factory() as db:
        await db.execute(
            text(
                "UPDATE containers SET status='error', "
                "error_message='simulated error for test', "
                "updated_at=now() WHERE id = :cid"
            ),
            {"cid": cid},
        )
        await db.commit()
    _docker_rm(_docker_name(cid))


# ---------------------------------------------------------------------------
# App fixtures for lifecycle integration (need admin_api_key for recover)
# ---------------------------------------------------------------------------


def _cleanup_lingering_agent_containers() -> None:
    """Force-remove any agent containers leftover from prior tests.

    This prevents resource contention when many integration tests run in the
    same session — earlier tests may leave containers running while their
    docker rm is still in progress, causing later readiness checks to time out.
    """
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    names = [n for n in result.stdout.splitlines() if n.startswith("agent-c-")]
    for name in names:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@pytest_asyncio.fixture
async def lifecycle_app(migrated_db, docker_network, agent_image, stub_llm):  # type: ignore[return]
    """Like seeded_app but also sets admin_api_key so /containers/{cid}/recover works."""
    # Remove any lingering agent containers from prior tests to prevent
    # docker resource contention causing readiness timeouts.
    _cleanup_lingering_agent_containers()

    from sqlalchemy import update

    from control_plane.app import create_app
    from control_plane.config import Settings
    from control_plane.db import make_engine, make_session_factory
    from control_plane.models_db import tenants
    from control_plane.seed import SEED_TENANT_LIMITS, apply_seed

    stub_llm_container_url, _host_url = stub_llm
    settings = Settings(
        database_url=migrated_db,
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seedkey",
        seed_llm_api_key="stub-key",
        agent_image_tag=agent_image,
        internal_network=docker_network,
        readyz_timeout_seconds=60,
        shim_port=8080,
        bind_shim_port_to_host=True,
        admin_api_key="boot-test-key",
        agent_extra_env={
            "ANTHROPIC_BASE_URL": stub_llm_container_url,
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "NO_PROXY": "*",
            "no_proxy": "*",
        },
    )
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    async with factory() as s:
        await apply_seed(s, settings)
        await s.execute(
            update(tenants)
            .where(tenants.c.id == settings.seed_tenant_id)
            .values(limits=SEED_TENANT_LIMITS)
        )
        await s.commit()
    # Seed the anthropic credential inline (mirrors conftest._seed_credential).
    import base64

    import sqlalchemy as sa

    from control_plane.credentials_service import build_credential_row
    from control_plane.tables import credentials as _creds_table

    _master_key = base64.b64decode(os.environ["CREDENTIAL_ENCRYPTION_KEY"])
    row = build_credential_row(
        tenant_id=settings.seed_tenant_id,
        provider="anthropic",
        api_key=settings.seed_llm_api_key,
        created_by=None,
        master_key=_master_key,
    )
    async with factory() as s:
        await s.execute(
            sa.delete(_creds_table).where(
                _creds_table.c.tenant_id == settings.seed_tenant_id,
                _creds_table.c.provider == "anthropic",
            )
        )
        await s.execute(sa.insert(_creds_table).values(**row))
        await s.commit()
    app = create_app(settings)

    # Wire docker_client and shim onto app.state directly since ASGITransport
    # does not run the FastAPI lifespan context.  The lifecycle ops (pause, recover)
    # need these to be set.
    import docker as _docker

    from control_plane.app import _ContainerShimDispatcher

    try:
        _docker_client = _docker.from_env()
    except Exception:  # noqa: BLE001
        _docker_client = None
    app.state.docker_client = _docker_client
    app.state.shim = (
        _ContainerShimDispatcher(factory, settings.shim_port)
        if _docker_client is not None
        else None
    )
    app.state.session_factory = factory

    yield app
    if _docker_client is not None:
        try:
            _docker_client.close()
        except Exception:  # noqa: BLE001
            pass
    await engine.dispose()


async def _create_container(
    c: AsyncClient,
    *,
    name: str = "lc",
    system_prompt: str | None = None,
) -> str:
    """Create a running container and return its id."""
    config: dict = {
        "driver": "vanilla",
        "model": "claude-opus-4-7",
        "tools": ["read_file", "write_file"],
    }
    if system_prompt is not None:
        config["system_prompt"] = system_prompt
    r = await c.post(
        "/v1/containers",
        headers=_HEADERS,
        json={"name": name, "config": config},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "running"
    return r.json()["id"]


async def _delete_container(c: AsyncClient, cid: str) -> None:
    """Best-effort DELETE of a container; ignores errors (teardown)."""
    try:
        await c.request(
            "DELETE",
            f"/v1/containers/{cid}",
            headers=_HEADERS,
        )
    except Exception:  # noqa: BLE001
        pass


async def _poll_task_terminal(
    c: AsyncClient, cid: str, task_id: str, *, max_wait: int = 60
) -> dict:
    """Poll GET /tasks/{task_id} until the task reaches a terminal status."""
    for _ in range(max_wait):
        resp = await c.get(
            f"/v1/containers/{cid}/tasks/{task_id}",
            headers=_HEADERS,
        )
        t = resp.json()
        if t["status"] in ("completed", "failed", "timed_out", "cancelled"):
            return t
        await asyncio.sleep(1)
    return t  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Test 1: pause(force) on a busy container cancels it; plain pause is 409
# ---------------------------------------------------------------------------


async def test_pause_force_cancels_inflight_then_plain_pause_rejected(
    lifecycle_app: object,
) -> None:
    """A plain pause on a busy container is 409; force-pause cancels and pauses."""
    async with await _client(lifecycle_app) as c:
        # Provision a container with SLOW system_prompt: stub LLM delays 5 s on turn 0.
        cid = await _create_container(c, name="pause-test", system_prompt="SLOW")
        try:
            # Submit a task that will keep the shim busy for ~5 s (SLOW delay).
            t = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=_HEADERS,
                json={"prompt": "slow task"},
            )
            assert t.status_code == 200, t.text
            task_id = t.json()["task_id"]
            assert t.json()["status"] == "running"

            # Plain pause while task is running → 409 container_not_runnable.
            r = await c.post(
                f"/v1/containers/{cid}/pause",
                headers=_HEADERS,
                json={},
            )
            assert r.status_code == 409, r.text
            assert r.json()["error"]["code"] == "container_not_runnable"

            # Force-pause: cancels in-flight tasks, then pauses the container.
            r2 = await c.post(
                f"/v1/containers/{cid}/pause",
                headers=_HEADERS,
                json={"force": True},
            )
            assert r2.status_code == 200, r2.text

            # Container must now be paused.
            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.json()["status"] == "paused", g.json()

            # Task ends in a terminal state (cancelled by force-pause or completed).
            final_task = await _poll_task_terminal(c, cid, task_id, max_wait=30)
            assert final_task["status"] in ("cancelled", "completed"), final_task

        finally:
            await _delete_container(c, cid)


# ---------------------------------------------------------------------------
# Test 2: archive then submit rehydrates from volume with workspace intact
# ---------------------------------------------------------------------------


async def test_archive_then_task_rehydrates_with_workspace_intact(
    lifecycle_app: object,
) -> None:
    """Archive a paused container; submit a task → it rehydrates and workspace file survives."""
    async with await _client(lifecycle_app) as c:
        cid = await _create_container(c, name="archive-test")
        try:
            # Write a file into the container workspace via the files API.
            put_r = await c.put(
                f"/v1/containers/{cid}/files/raw",
                headers=_HEADERS,
                params={"path": "note.txt"},
                content=b"keepme",
            )
            assert put_r.status_code == 204, put_r.text

            # Pause the container (it is idle; no tasks running).
            pause_r = await c.post(
                f"/v1/containers/{cid}/pause",
                headers=_HEADERS,
                json={},
            )
            assert pause_r.status_code == 200, pause_r.text

            # Archive by calling lifecycle.archive directly (skips the dormant timer).
            await _archive_via_lifecycle(lifecycle_app, cid)

            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.json()["status"] == "archived", g.json()

            # The Docker container is gone; the volume remains.
            assert not _docker_container_exists(_docker_name(cid)), (
                f"Expected Docker container {_docker_name(cid)!r} to be removed after archive"
            )
            assert _docker_volume_exists(_volume_name(cid)), (
                f"Expected Docker volume {_volume_name(cid)!r} to remain after archive"
            )

            # Submit a task → rehydrates from the volume, runs.
            t = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=_HEADERS,
                json={"prompt": "read note"},
            )
            assert t.status_code == 200, t.text
            task_id = t.json()["task_id"]

            # Container transitions to running (rehydrated).
            g2 = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g2.json()["status"] == "running", g2.json()

            # The file must survive the rehydration (same volume).
            f = await c.get(
                f"/v1/containers/{cid}/files/raw",
                headers=_HEADERS,
                params={"path": "note.txt"},
            )
            assert f.content == b"keepme", f"expected b'keepme', got {f.content!r}"

            # Wait for the task to complete to avoid teardown conflicts.
            await _poll_task_terminal(c, cid, task_id, max_wait=60)

        finally:
            await _delete_container(c, cid)


# ---------------------------------------------------------------------------
# Test 3: reconciler reconciles a docker-killed container; next task resumes it
# ---------------------------------------------------------------------------


async def test_reconciler_reconciles_killed_container(
    lifecycle_app: object,
) -> None:
    """docker kill a running container; reconcile_all brings it back; next task resumes."""
    async with await _client(lifecycle_app) as c:
        cid = await _create_container(c, name="reconcile-test")
        try:
            # Confirm it is idle-running.
            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.json()["status"] == "running"

            # Hard-kill the container out from under the DB.
            # DB still says running; Docker container is dead (exit 137).
            _docker_kill(_docker_name(cid))

            # Give Docker a moment to register the exit.
            await asyncio.sleep(1)

            # Run the reconciler — should detect the mismatch and take action.
            await _reconcile_via_app(lifecycle_app)

            # Status should be either running (recovered) or paused (clean exit path).
            # docker kill produces exit 137 → non-zero → RECOVER → running.
            g2 = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            status_after_reconcile = g2.json()["status"]
            assert status_after_reconcile in ("running", "paused", "recovering", "error"), (
                f"Unexpected status after reconcile: {status_after_reconcile}"
            )

            # The next task must succeed and bring the container to running.
            t = await c.post(
                f"/v1/containers/{cid}/tasks",
                headers=_HEADERS,
                json={"prompt": "hello"},
            )
            assert t.status_code == 200, t.text
            task_id = t.json()["task_id"]

            g3 = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g3.json()["status"] == "running", g3.json()

            # Wait for task completion.
            final_task = await _poll_task_terminal(c, cid, task_id, max_wait=60)
            assert final_task["status"] in ("completed", "failed"), final_task

        finally:
            await _delete_container(c, cid)


# ---------------------------------------------------------------------------
# Test 4: recover from error returns to running against the same volume
# ---------------------------------------------------------------------------


async def test_recover_from_error_returns_to_running_same_volume(
    lifecycle_app: object,
) -> None:
    """Force a container to error; recover → running; workspace file survives."""
    async with await _client(lifecycle_app) as c:
        cid = await _create_container(c, name="recover-test")
        try:
            # Write a file that must survive the recover re-provision.
            put_r = await c.put(
                f"/v1/containers/{cid}/files/raw",
                headers=_HEADERS,
                params={"path": "keep.txt"},
                content=b"data",
            )
            assert put_r.status_code == 204, put_r.text

            # Force the container into error (docker rm + db update).
            await _force_error_via_db(lifecycle_app, cid)

            g = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g.json()["status"] == "error", g.json()

            # Recover via the admin endpoint.
            r = await c.post(
                f"/v1/containers/{cid}/recover",
                headers=_ADMIN_HEADERS,
            )
            assert r.status_code == 200, r.text

            g2 = await c.get(f"/v1/containers/{cid}", headers=_HEADERS)
            assert g2.json()["status"] == "running", g2.json()

            # File must survive (same volume path).
            f = await c.get(
                f"/v1/containers/{cid}/files/raw",
                headers=_HEADERS,
                params={"path": "keep.txt"},
            )
            assert f.content == b"data", f"expected b'data', got {f.content!r}"

            # recover on a non-error container must return 409.
            r2 = await c.post(
                f"/v1/containers/{cid}/recover",
                headers=_ADMIN_HEADERS,
            )
            assert r2.status_code == 409, r2.text

        finally:
            await _delete_container(c, cid)


# ---------------------------------------------------------------------------
# Test 5: admission/LRU with max_running_containers=1
# ---------------------------------------------------------------------------


async def test_admission_lru_pause_and_503(
    lifecycle_app: object,
) -> None:
    """With max_running_containers=1: idle container LRU-paused; busy container → 503."""
    from sqlalchemy import update

    from control_plane.models_db import tenants

    session_factory = lifecycle_app.state.session_factory  # type: ignore[attr-defined]

    async with await _client(lifecycle_app) as c:
        # Create containers A and B while the limit is still high (they both provision
        # to running), then set limit=1 once both exist.
        cid_a = await _create_container(c, name="lru-a")
        cid_b = await _create_container(c, name="lru-b")

        try:
            # Pause B so the slot picture is deterministic:
            # A running (slot 1), B paused (slot 0) — within the limit we're about to set.
            pause_b = await c.post(
                f"/v1/containers/{cid_b}/pause",
                headers=_HEADERS,
                json={},
            )
            assert pause_b.status_code == 200, pause_b.text

            # Now enforce the cap of 1 (A is the sole live container).
            async with session_factory() as db:
                await db.execute(
                    update(tenants)
                    .where(tenants.c.id == "ten_seed")
                    .values(
                        limits={
                            "max_containers": 2000,
                            "max_running_containers": 1,
                            "max_users": 25,
                            "max_concurrent_tasks_per_container": 4,
                            "max_workspace_volume_size_mb": 10240,
                            "default_task_timeout_seconds": 1800,
                            "default_max_iterations": 30,
                            "default_max_tokens": 2000000,
                            "idle_pause_minutes": 20,
                            "archive_after_hours": 72,
                            "reclaim_after_days": 30,
                            "allowed_drivers": ["vanilla", "opencode"],
                            "allowed_models": ["claude-opus-4-7", "claude-sonnet-4-6"],
                        }
                    )
                )
                await db.commit()

            # Submit to B: A is idle → LRU-paused to free the slot, B resumes and runs.
            t = await c.post(
                f"/v1/containers/{cid_b}/tasks",
                headers=_HEADERS,
                json={"prompt": "hi"},
            )
            assert t.status_code == 200, t.text
            task_id_b = t.json()["task_id"]

            ga = await c.get(f"/v1/containers/{cid_a}", headers=_HEADERS)
            assert ga.json()["status"] == "paused", (
                f"Expected A to be LRU-paused; got {ga.json()['status']!r}"
            )
            gb = await c.get(f"/v1/containers/{cid_b}", headers=_HEADERS)
            assert gb.json()["status"] == "running", (
                f"Expected B to be running; got {gb.json()['status']!r}"
            )

            # Wait for task_id_b to complete so B is no longer busy.
            final_b = await _poll_task_terminal(c, cid_b, task_id_b, max_wait=60)
            assert final_b["status"] in ("completed", "failed"), final_b

            # Now submit a SLOW task to B (makes it busy).
            # B is running and now has a SLOW task keeping it busy.
            # We need to re-provision B with SLOW or patch the config.
            # Instead: submit a SLOW task (embed SLOW in the prompt — the stub checks system).
            # The stub checks if SLOW is in the *system* prompt, not user prompt.
            # So we patch B's config to add SLOW system_prompt temporarily.
            # Actually simpler: re-create or just proceed — the limit is 1 and A is paused.
            # A is paused, B is running idle. Submit SLOW task to B to keep it busy.
            long_t = await c.post(
                f"/v1/containers/{cid_b}/tasks",
                headers=_HEADERS,
                json={"prompt": "SLOW task"},
            )
            # The SLOW system_prompt is not active; this task will complete quickly.
            # We need B to be genuinely busy when we submit to A.
            # To make B busy: patch its system_prompt to include SLOW, then submit.

            # Patch B's config to use SLOW system prompt.
            patch_r = await c.patch(
                f"/v1/containers/{cid_b}/config",
                headers=_HEADERS,
                json={
                    "driver": "vanilla",
                    "model": "claude-opus-4-7",
                    "tools": ["read_file", "write_file"],
                    "system_prompt": "SLOW",
                },
            )
            assert patch_r.status_code == 200, patch_r.text

            # Wait for the quick task to finish.
            if long_t.status_code == 200:
                tid_quick = long_t.json()["task_id"]
                await _poll_task_terminal(c, cid_b, tid_quick, max_wait=60)

            # Submit the SLOW task to B — will keep it busy for ~5s.
            slow_t = await c.post(
                f"/v1/containers/{cid_b}/tasks",
                headers=_HEADERS,
                json={"prompt": "slow busy task"},
            )
            assert slow_t.status_code == 200, slow_t.text

            # Give the shim a moment to accept the task.
            await asyncio.sleep(0.5)

            # A is paused; bringing it up requires freeing a slot.
            # B is busy → no idle container to LRU-pause → 503.
            r = await c.post(
                f"/v1/containers/{cid_a}/tasks",
                headers=_HEADERS,
                json={"prompt": "hi"},
            )
            assert r.status_code == 503, r.text
            assert r.json()["error"]["code"] == "running_capacity_exhausted", r.json()

            # Wait for the slow task to complete before teardown.
            slow_tid = slow_t.json()["task_id"]
            await _poll_task_terminal(c, cid_b, slow_tid, max_wait=60)

        finally:
            await _delete_container(c, cid_a)
            await _delete_container(c, cid_b)

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

import docker
from docker.errors import NotFound

from control_plane.config import Settings
from control_plane.docker_ctl import host_shim_url_from_ports
from control_plane.ids import docker_name_for, volume_name_for
from control_plane.shim_client import ShimClient


@dataclass
class ProvisionResult:
    docker_name: str
    volume_name: str
    shim_token: str
    # When the shim port is bound to the host (test / non-overlay network
    # environments where Docker container names do not resolve from the host),
    # this holds the host-accessible URL to use instead of the internal URL.
    host_shim_url: str | None = None


class ReadinessFailed(Exception):
    """The shim did not become ready within the timeout."""


def _docker_client() -> docker.DockerClient:
    return docker.from_env()


def _env_for(
    container_id: str, tenant_id: str, shim_token: str, max_workers: int
) -> dict[str, str]:
    return {
        "SHIM_TOKEN": shim_token,
        "CONTAINER_ID": container_id,
        "TENANT_ID": tenant_id,
        "SHIM_MAX_WORKERS": str(max_workers),
        "SEARCH_PROVIDER_URL": "http://searxng:8080",
        "HTTP_PROXY": "http://egress-proxy:8888",
        "HTTPS_PROXY": "http://egress-proxy:8888",
        # ALL_PROXY covers clients that ignore the scheme-specific vars — notably
        # codex's MCP OAuth-discovery reqwest client, which otherwise bypasses
        # the proxy and stalls startup ~40s on well-known probes that fail DNS.
        "ALL_PROXY": "http://egress-proxy:8888",
        "NO_PROXY": "localhost,127.0.0.1,searxng",
    }


def _agent_image_ref(agent_registry: str, image_tag: str) -> str:
    repo = f"agent-runtime:{image_tag}"
    return f"{agent_registry}/{repo}" if agent_registry else repo


class ImageUnavailable(RuntimeError):
    """Raised when the requested agent image cannot be pulled or found."""


def pull_or_verify_image(client: docker.DockerClient, settings: Settings, image_tag: str) -> str:
    """Make image_tag available for a container recreate, returning its ref.

    With a registry configured, force-pull so moving tags (e.g. ``dev``/``latest``)
    fetch the newest build. In local-only mode (no registry), verify the image is
    already on the daemon (covers locally-built dev images). Raise
    ``ImageUnavailable`` if the image cannot be obtained — callers MUST treat this
    as a no-op failure and leave the container untouched.
    """
    ref = _agent_image_ref(settings.agent_registry, image_tag)
    if settings.agent_registry:
        auth: dict[str, str] | None = None
        if settings.agent_registry_username:
            auth = {
                "username": settings.agent_registry_username,
                "password": settings.agent_registry_password,
            }
        try:
            client.images.pull(ref, auth_config=auth)
        except docker.errors.DockerException as e:  # covers APIError + connection/DNS failures
            raise ImageUnavailable(f"could not pull {ref}: {e}") from e
    else:
        try:
            client.images.get(ref)
        except docker.errors.ImageNotFound as e:
            raise ImageUnavailable(f"image {ref} not found locally") from e
    return ref


def build_run_kwargs(
    *,
    settings: Settings,
    docker_name: str,
    cid: str,
    tenant_id: str,
    shim_token: str,
    max_concurrent_tasks: int,
    image_tag: str,
    mem_limit: str,
    cpus: float,
) -> dict[str, object]:
    """Return the ``docker_client.containers.run`` keyword-arguments dict for an
    agent container wired to the production networking (spec §4.7, §8.1).

    Pure function (no docker calls) so it is unit-testable without a daemon.

    The image **registry prefix** and resource caps come from ``settings`` (global,
    env-tunable: registry for pull-based provisioning; mem/cpu/pids for VM sizing).
    The image **tag** comes from the ``image_tag`` parameter — the per-container
    resolved value (create-request override, or the stored DB tag on recreate) —
    NOT ``settings.agent_image_tag``, so per-agent image pinning is preserved.
    ``provision_container`` calls this and overlays volumes / ports / ulimits.

    The agent is attached to ``agent-runtime-internal`` **only** so its sole
    outbound path is the egress proxy via ``HTTP_PROXY`` / ``HTTPS_PROXY``.
    """
    return {
        "image": _agent_image_ref(settings.agent_registry, image_tag),
        "name": docker_name,
        "hostname": docker_name,
        "detach": True,
        "network": settings.internal_network,
        "read_only": True,
        "tmpfs": {
            "/tmp": "size=512m,exec",
            "/var/tmp": "size=128m",
            "/home/agent": "size=256m,exec",
        },
        "user": "0:0",
        "cap_drop": ["ALL"],
        # KILL lets the root shim SIGTERM the agent-uid driver child on
        # timeout/cancel; without it kill() across uids returns EPERM. Only
        # root (the shim) can use it — the agent uid stays unprivileged under
        # no-new-privileges.
        "cap_add": ["CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "KILL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": settings.agent_pids_limit,
        "mem_limit": mem_limit,
        "memswap_limit": mem_limit,
        "nano_cpus": int(cpus * 1_000_000_000),
        "restart_policy": {"Name": "no"},
        "environment": _env_for(cid, tenant_id, shim_token, max_concurrent_tasks),
        "labels": {
            "agent-runtime.tenant_id": tenant_id,
            "agent-runtime.container_id": cid,
        },
    }


async def provision_container(
    *,
    settings: Settings,
    container_id: str,
    tenant_id: str,
    image_tag: str,
    max_workers: int,
    mem_limit: str,
    cpus: float,
    reuse_volume_name: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> ProvisionResult:
    """Create the volume + container, start it, poll /readyz. On failure remove
    the partial container and the volume we created (a reused volume is left intact),
    then raise ReadinessFailed — caller persists no row (spec §4.7).

    When ``settings.bind_shim_port_to_host`` is True (useful when the control
    plane runs on the Docker host rather than inside the Docker network, e.g. in
    integration tests on macOS), the shim port is bound to a random host port
    and the returned ``host_shim_url`` reflects that host-accessible endpoint.
    """
    client = _docker_client()
    docker_name = docker_name_for(container_id)
    shim_token = secrets.token_urlsafe(32)

    created_volume = False
    if reuse_volume_name is not None:
        volume_name = reuse_volume_name
    else:
        volume_name = volume_name_for(container_id)
        await asyncio.to_thread(client.volumes.create, name=volume_name)
        created_volume = True

    bind_to_host = settings.bind_shim_port_to_host
    shim_port = settings.shim_port

    def _run() -> docker.models.containers.Container:
        kwargs = build_run_kwargs(
            settings=settings,
            docker_name=docker_name,
            cid=container_id,
            tenant_id=tenant_id,
            shim_token=shim_token,
            max_concurrent_tasks=max_workers,
            image_tag=image_tag,   # the resolved per-container tag passed into provision_container
            mem_limit=mem_limit,
            cpus=cpus,
        )
        # Daemon-only overlays not in the pure kwargs:
        kwargs["volumes"] = {volume_name: {"bind": "/workspace", "mode": "rw"}}
        kwargs["ulimits"] = [docker.types.Ulimit(name="nofile", soft=4096, hard=4096)]
        kwargs["environment"] = {
            **kwargs["environment"],  # type: ignore[dict-item]
            **(extra_env or {}),
        }
        kwargs["labels"] = {
            **kwargs["labels"],  # type: ignore[dict-item]
            "agent-runtime.version": image_tag,
        }
        if bind_to_host:
            kwargs["ports"] = {f"{shim_port}/tcp": None}
        return client.containers.run(**kwargs)

    try:
        # Pull (registry path) is inside the cleanup scope so a pull failure also
        # removes the volume we just created — honoring the docstring contract.
        # Force-pulling on a configured registry means a newly created container
        # always gets the latest image pushed under its (moving) tag rather than a
        # stale local cache; local-only mode verifies the image is present.
        await asyncio.to_thread(pull_or_verify_image, client, settings, image_tag)
        cont: docker.models.containers.Container = await asyncio.to_thread(_run)
    except Exception:
        if created_volume:
            await _safe_remove_volume(client, volume_name)
        raise

    # Resolve the base URL for the shim readiness check.
    host_shim_url: str | None = None
    if bind_to_host:
        # Reload to get the assigned host port.
        await asyncio.to_thread(cont.reload)
        host_shim_url = host_shim_url_from_ports(cont.ports or {}, shim_port)
        base_url = host_shim_url or f"http://{docker_name}:{shim_port}"
    else:
        base_url = f"http://{docker_name}:{shim_port}"

    ready = await _poll_readyz(base_url, shim_token, settings.readyz_timeout_seconds)
    if not ready:
        await _teardown(client, docker_name, volume_name if created_volume else None)
        raise ReadinessFailed(
            f"{docker_name} not ready within {settings.readyz_timeout_seconds}s"
        )

    return ProvisionResult(
        docker_name=docker_name,
        volume_name=volume_name,
        shim_token=shim_token,
        host_shim_url=host_shim_url,
    )


async def _poll_readyz(base_url: str, token: str, timeout_s: float) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with ShimClient(base_url=base_url, token=token, timeout=5.0) as shim:
        while asyncio.get_event_loop().time() < deadline:
            if await shim.readyz():
                return True
            await asyncio.sleep(0.5)
    return False


async def _safe_remove_volume(client: docker.DockerClient, volume_name: str) -> None:
    try:
        vol = await asyncio.to_thread(client.volumes.get, volume_name)
        await asyncio.to_thread(vol.remove, force=True)
    except NotFound:
        pass


async def _teardown(
    client: docker.DockerClient, docker_name: str, volume_name: str | None
) -> None:
    try:
        cont = await asyncio.to_thread(client.containers.get, docker_name)
        await asyncio.to_thread(cont.remove, force=True)
    except NotFound:
        pass
    if volume_name is not None:
        await _safe_remove_volume(client, volume_name)


async def destroy_container(
    *, docker_name: str, volume_name: str, delete_volume: bool
) -> None:
    """Stop+remove the container; remove the volume only if delete_volume."""
    client = _docker_client()
    await _teardown(client, docker_name, volume_name if delete_volume else None)

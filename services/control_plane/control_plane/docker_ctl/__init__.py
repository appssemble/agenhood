"""docker_ctl package — provisioning (provision.py) + lifecycle wrappers (this module).

Lifecycle wrappers run blocking Docker SDK calls in a thread via asyncio.to_thread
so they are safely awaitable from the async control-plane event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import docker.errors


@dataclass(frozen=True)
class DockerStateInfo:
    """Snapshot of Docker container state returned by :func:`inspect_state`."""

    present: bool
    status: str | None  # "running" | "exited" | "created" | "paused" | ... | None if absent
    exit_code: int | None
    oom_killed: bool


async def stop(client: object, docker_name: str, grace_seconds: int) -> None:
    """Stop a running container; silently ignores NotFound (already gone)."""

    def _stop() -> None:
        try:
            c = client.containers.get(docker_name)  # type: ignore[attr-defined]
        except docker.errors.NotFound:
            return
        c.stop(timeout=grace_seconds)

    await asyncio.to_thread(_stop)


async def start(client: object, docker_name: str) -> None:
    """Start a stopped container."""

    def _start() -> None:
        client.containers.get(docker_name).start()  # type: ignore[attr-defined]

    await asyncio.to_thread(_start)


def host_shim_url_from_ports(ports: Any, shim_port: int) -> str | None:
    """Return ``http://localhost:<host_port>`` for *shim_port*'s first host binding.

    Pure helper over a Docker ``container.ports`` mapping (shape
    ``{"<port>/tcp": [{"HostPort": "…"}], …}``). Returns None when there is no
    host binding for *shim_port* (e.g. in-network-only containers).
    """
    bindings = (ports or {}).get(f"{shim_port}/tcp") or []
    if bindings:
        return f"http://localhost:{int(bindings[0]['HostPort'])}"
    return None


async def get_host_shim_url(
    client: object, docker_name: str, shim_port: int
) -> str | None:
    """Return the host-accessible shim URL after a container has been started.

    Docker re-assigns ephemeral host ports on every ``docker start`` when the
    container was originally run with ``-p 0:<shim_port>``.  This helper
    reloads the container's port bindings and returns the new URL so the caller
    can update ``resources._host_shim_url`` in the DB.

    Returns None if the container has no host port binding for *shim_port*
    (e.g. in-network-only containers that do not need host port binding).
    """

    def _get() -> str | None:
        try:
            c = client.containers.get(docker_name)  # type: ignore[attr-defined]
            c.reload()
            return host_shim_url_from_ports(c.ports or {}, shim_port)
        except Exception:  # noqa: BLE001
            return None

    return await asyncio.to_thread(_get)


async def rm(client: object, docker_name: str) -> None:
    """Remove the container object. Never touches the workspace volume."""

    def _rm() -> None:
        try:
            c = client.containers.get(docker_name)  # type: ignore[attr-defined]
        except docker.errors.NotFound:
            return
        c.remove(force=True)

    await asyncio.to_thread(_rm)


async def volume_rm(client: object, volume_name: str) -> None:
    """Remove a named Docker volume; silently ignores NotFound.

    The docker SDK's ``VolumeCollection`` has no ``remove`` method — a volume is
    removed by fetching it and calling ``Volume.remove(force=True)`` (same shape
    as ``_safe_remove_volume`` in provision.py).
    """

    def _vrm() -> None:
        try:
            vol = client.volumes.get(volume_name)  # type: ignore[attr-defined]
        except docker.errors.NotFound:
            return
        vol.remove(force=True)

    await asyncio.to_thread(_vrm)


async def exists(client: object, docker_name: str) -> bool:
    """Return True if the container exists (any status), False if NotFound."""

    def _exists() -> bool:
        try:
            client.containers.get(docker_name)  # type: ignore[attr-defined]
            return True
        except docker.errors.NotFound:
            return False

    return await asyncio.to_thread(_exists)


async def run_from_volume(
    client: object,
    row: dict[str, object],
    *,
    settings: Any = None,
    network: str | None = None,
    shim_port: int | None = None,
    bind_to_host: bool = False,
    extra_env: dict[str, str] | None = None,
) -> str | None:
    """Re-provision a container from its existing workspace volume (rehydrate / recover path).

    Uses the same docker_name, volume_name, and image_tag that are stored in
    the container row.  A fresh shim_token should be minted by the caller
    (or the row's existing token reused if the shim has not been rotated).

    When ``bind_to_host`` is True and ``shim_port`` is provided, the shim port
    is bound to a random ephemeral host port (same behaviour as provision_container).
    Returns the host-accessible shim URL when port binding is used, else None.

    The actual ``client.containers.run()`` call mirrors the provisioning
    module's ``_run()`` helper; the integration test (Task 13) exercises the
    real path.  Unit tests monkeypatch this function.
    """
    result_container: list[object] = []

    def _run() -> None:
        docker_name = str(row["docker_name"])
        volume_name = str(row["volume_name"])
        image_tag = str(row.get("image_tag", "latest"))
        shim_token = str(row.get("shim_token", ""))
        container_id = str(row.get("id", docker_name))
        tenant_id = str(row.get("tenant_id", ""))

        ports: dict[str, int | None] | None = None
        if bind_to_host and shim_port is not None:
            ports = {f"{shim_port}/tcp": None}

        # Reuse the canonical run kwargs so rehydrated/recovered containers get
        # the SAME security posture as initial provisioning: root user (the
        # entrypoint drops to the agent uid for untrusted work), dropped caps,
        # read-only rootfs, and the egress-proxy env (HTTP_PROXY/HTTPS_PROXY —
        # the internal network blocks direct egress). This path previously built
        # a minimal kwargs dict that omitted `user`/caps, so the container ran as
        # the image-default agent uid and the root entrypoint's workspace setup
        # failed with EPERM, crashing the container on boot.
        from control_plane.config import Settings  # noqa: PLC0415
        from control_plane.docker_ctl.provision import build_run_kwargs  # noqa: PLC0415

        # build_run_kwargs needs Settings for the registry prefix + resource caps so
        # recovered/rehydrated agents resolve the SAME (registry-prefixed) image ref
        # as initial provisioning. Fall back to env defaults when a caller did not
        # thread settings — preserves the legacy bare-local "agent-runtime:<tag>".
        _settings = settings if settings is not None else Settings.from_env()
        max_workers = int(row.get("max_concurrent_tasks") or 1)
        kwargs: dict[str, object] = build_run_kwargs(
            settings=_settings,
            docker_name=docker_name,
            cid=container_id,
            tenant_id=tenant_id,
            shim_token=shim_token,
            max_concurrent_tasks=max_workers,
            image_tag=image_tag,
        )
        kwargs["volumes"] = {volume_name: {"bind": "/workspace", "mode": "rw"}}
        if extra_env:
            kwargs["environment"] = {**kwargs["environment"], **extra_env}  # type: ignore[dict-item]
        if network is not None:
            kwargs["network"] = network
        if ports is not None:
            kwargs["ports"] = ports

        cont = client.containers.run(**kwargs)  # type: ignore[attr-defined]
        result_container.append(cont)

    await asyncio.to_thread(_run)

    if not bind_to_host or shim_port is None or not result_container:
        return None

    # Reload to get the assigned host port.
    cont = result_container[0]

    def _reload() -> dict[str, object]:
        cont.reload()  # type: ignore[attr-defined]
        return cont.ports or {}  # type: ignore[attr-defined]

    ports_info = await asyncio.to_thread(_reload)
    return host_shim_url_from_ports(ports_info, shim_port)


async def inspect_state(client: object, docker_name: str) -> DockerStateInfo:
    """Return a lightweight snapshot of container state.

    Returns a :class:`DockerStateInfo` with ``present=False`` when the
    container does not exist; the caller (reconciler) uses this to determine
    the appropriate reconcile action.
    """

    def _inspect() -> DockerStateInfo:
        try:
            c = client.containers.get(docker_name)  # type: ignore[attr-defined]
        except docker.errors.NotFound:
            return DockerStateInfo(
                present=False, status=None, exit_code=None, oom_killed=False
            )
        c.reload()
        st = c.attrs.get("State", {})
        return DockerStateInfo(
            present=True,
            status=st.get("Status"),
            exit_code=st.get("ExitCode"),
            oom_killed=bool(st.get("OOMKilled", False)),
        )

    return await asyncio.to_thread(_inspect)

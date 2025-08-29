from __future__ import annotations

import pytest

from control_plane import docker_ctl

pytestmark = pytest.mark.unit


class FakeContainer:
    def __init__(self, name: str, status: str = "running"):
        self.name = name
        self.status = status
        self.stopped = False
        self.started = False
        self.removed = False
        self.attrs = {"State": {"Status": status, "ExitCode": 0, "OOMKilled": False}}

    def stop(self, timeout: int | None = None) -> None:
        self.stopped = True
        self.status = "exited"
        self.attrs["State"]["Status"] = "exited"

    def start(self) -> None:
        self.started = True
        self.status = "running"
        self.attrs["State"]["Status"] = "running"

    def remove(self, force: bool = False) -> None:
        self.removed = True

    def reload(self) -> None:
        pass


class FakeVolume:
    def __init__(self, name: str, parent: FakeVolumes):
        self.name = name
        self._parent = parent

    def remove(self, force: bool = False) -> None:
        self._parent.removed.append(self.name)


class FakeVolumes:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def get(self, name: str) -> FakeVolume:  # mirrors docker SDK VolumeCollection.get
        return FakeVolume(name, self)


class FakeDocker:
    def __init__(self, containers: list[FakeContainer]):
        self._by_name = {c.name: c for c in containers}
        self.containers = self
        self.volumes = FakeVolumes()

    def get(self, name: str) -> FakeContainer:
        import docker.errors

        if name not in self._by_name:
            raise docker.errors.NotFound(name)
        return self._by_name[name]


@pytest.mark.asyncio
async def test_stop_calls_docker_stop_with_grace() -> None:
    c = FakeContainer("agent-c-abc")
    fake = FakeDocker([c])
    await docker_ctl.stop(fake, "agent-c-abc", grace_seconds=15)
    assert c.stopped is True


@pytest.mark.asyncio
async def test_exists_true_then_false() -> None:
    c = FakeContainer("agent-c-abc")
    fake = FakeDocker([c])
    assert await docker_ctl.exists(fake, "agent-c-abc") is True
    assert await docker_ctl.exists(fake, "agent-c-missing") is False


@pytest.mark.asyncio
async def test_rm_removes_container_keeps_volume() -> None:
    c = FakeContainer("agent-c-abc", status="exited")
    fake = FakeDocker([c])
    await docker_ctl.rm(fake, "agent-c-abc")
    assert c.removed is True
    assert fake.volumes.removed == []  # rm never touches the volume


@pytest.mark.asyncio
async def test_volume_rm_removes_named_volume() -> None:
    fake = FakeDocker([])
    await docker_ctl.volume_rm(fake, "agent-vol-abc")
    assert "agent-vol-abc" in fake.volumes.removed


@pytest.mark.asyncio
async def test_inspect_returns_docker_state_for_present_container() -> None:
    c = FakeContainer("agent-c-abc", status="running")
    fake = FakeDocker([c])
    state = await docker_ctl.inspect_state(fake, "agent-c-abc")
    assert state.present is True
    assert state.status == "running"
    assert state.oom_killed is False


@pytest.mark.asyncio
async def test_inspect_missing_container_reports_absent() -> None:
    fake = FakeDocker([])
    state = await docker_ctl.inspect_state(fake, "agent-c-missing")
    assert state.present is False

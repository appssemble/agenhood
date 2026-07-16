from __future__ import annotations

import docker.errors
import pytest

from control_plane.config import Settings
from control_plane.docker_ctl.provision import (
    ImageUnavailable,
    pull_or_verify_image,
)

pytestmark = pytest.mark.unit


def _settings(**kw) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seed",
        seed_llm_api_key="",
        agent_image_tag="dev",
        internal_network="test",
        readyz_timeout_seconds=1.0,
        shim_port=8080,
    )
    base.update(kw)
    return Settings(**base)


class _Images:
    def __init__(self, *, pull_exc=None, get_exc=None) -> None:
        self.pull_exc = pull_exc
        self.get_exc = get_exc
        self.pulled: list[tuple] = []
        self.got: list[str] = []

    def pull(self, ref, auth_config=None):
        self.pulled.append((ref, auth_config))
        if self.pull_exc:
            raise self.pull_exc

    def get(self, ref):
        self.got.append(ref)
        if self.get_exc:
            raise self.get_exc


class _Client:
    def __init__(self, images: _Images) -> None:
        self.images = images


def test_registry_if_not_present_skips_pull_when_local() -> None:
    imgs = _Images()  # get succeeds => image present
    s = _settings(agent_registry="reg.example")
    ref = pull_or_verify_image(_Client(imgs), s, "v2")
    assert ref == "reg.example/agent-runtime:v2"
    assert imgs.got == ["reg.example/agent-runtime:v2"]
    assert imgs.pulled == []


def test_registry_if_not_present_pulls_when_absent_with_auth() -> None:
    imgs = _Images(get_exc=docker.errors.ImageNotFound("missing"))
    s = _settings(
        agent_registry="reg.example",
        agent_registry_username="u",
        agent_registry_password="p",
    )
    ref = pull_or_verify_image(_Client(imgs), s, "v2")
    assert ref == "reg.example/agent-runtime:v2"
    assert imgs.pulled == [("reg.example/agent-runtime:v2", {"username": "u", "password": "p"})]


def test_registry_policy_always_force_pulls_without_local_check() -> None:
    imgs = _Images()
    s = _settings(agent_registry="reg.example", agent_image_pull_policy="always")
    pull_or_verify_image(_Client(imgs), s, "v2")
    assert imgs.pulled == [("reg.example/agent-runtime:v2", None)]
    assert imgs.got == []


def test_registry_force_overrides_if_not_present() -> None:
    imgs = _Images()  # image present locally
    s = _settings(agent_registry="reg.example")
    pull_or_verify_image(_Client(imgs), s, "v2", force=True)
    assert imgs.pulled == [("reg.example/agent-runtime:v2", None)]
    assert imgs.got == []


def test_pull_failure_raises_image_unavailable() -> None:
    imgs = _Images(
        pull_exc=docker.errors.APIError("no such tag"),
        get_exc=docker.errors.ImageNotFound("missing"),
    )
    s = _settings(agent_registry="reg.example", agent_registry_username="u")
    with pytest.raises(ImageUnavailable):
        pull_or_verify_image(_Client(imgs), s, "nope")


def test_pull_docker_exception_raises_image_unavailable() -> None:
    """A connection-level failure (registry down / DNS miss) must map to ImageUnavailable.

    docker.errors.DockerException is the base class for all docker-sdk errors.
    Catching it means a registry that is unreachable during images.pull yields a
    422 (image_unavailable) rather than leaking a 500 from an uncaught exception.
    """
    imgs = _Images(
        pull_exc=docker.errors.DockerException("connection refused"),
        get_exc=docker.errors.ImageNotFound("missing"),
    )
    s = _settings(agent_registry="reg.example")
    with pytest.raises(ImageUnavailable):
        pull_or_verify_image(_Client(imgs), s, "v2")


def test_local_only_verifies_presence() -> None:
    imgs = _Images()
    s = _settings(agent_registry="")
    ref = pull_or_verify_image(_Client(imgs), s, "dev")
    assert ref == "agent-runtime:dev"
    assert imgs.got == ["agent-runtime:dev"]
    assert imgs.pulled == []


def test_local_only_missing_raises_image_unavailable() -> None:
    imgs = _Images(get_exc=docker.errors.ImageNotFound("missing"))
    s = _settings(agent_registry="")
    with pytest.raises(ImageUnavailable):
        pull_or_verify_image(_Client(imgs), s, "ghost")

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys

import pytest
import pytest_asyncio

INTERNAL_NETWORK = "agent-runtime-internal-test"
AGENT_IMAGE_TAG = "test"
STUB_LLM_NAME = "stub-llm-test"

# Fixed 32-byte AES key used across the integration test session.
# base64-encoded so it can be set as the CREDENTIAL_ENCRYPTION_KEY env var.
_TEST_MASTER_KEY_B64 = base64.b64encode(b"A" * 32).decode()
_TEST_MASTER_KEY: bytes = base64.b64decode(_TEST_MASTER_KEY_B64)

# Ensure the env var is set for every subprocess + import that calls load_key_from_env().
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", _TEST_MASTER_KEY_B64)

# Paths computed relative to this conftest file.
# __file__ is  .../services/control_plane/tests/integration/conftest.py
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))           # integration/
_TESTS_DIR = os.path.dirname(_THIS_DIR)                          # tests/
_CP_DIR = os.path.dirname(_TESTS_DIR)                            # services/control_plane/

# Use the alembic from the SAME environment running pytest. This works for a
# local virtualenv (services/control_plane/.venv) and a CI system install
# alike. The previous hardcoded "<repo_root>/.venv/bin/alembic" existed in
# NEITHER environment (CI uses a system pip install; local uses the
# control_plane .venv), so it broke every integration test. Fall back to PATH.
_VENV_ALEMBIC = os.path.join(os.path.dirname(sys.executable), "alembic")
if not os.path.exists(_VENV_ALEMBIC):
    _VENV_ALEMBIC = shutil.which("alembic") or _VENV_ALEMBIC


def _run(cmd: list[str], **kwargs: object) -> None:
    subprocess.run(cmd, check=True, **kwargs)  # type: ignore[call-overload]


@pytest.fixture(scope="session")
def docker_network():  # type: ignore[return]
    """Create a bridge Docker network for the integration test session.

    Note: We do NOT use --internal because internal networks block port binding,
    which we need to make the shim accessible from the macOS host. In production
    the control plane runs inside Docker on the same network, so port binding is
    not required and --internal can be used for egress isolation.
    """
    subprocess.run(
        ["docker", "network", "create", INTERNAL_NETWORK],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    yield INTERNAL_NETWORK
    subprocess.run(
        ["docker", "network", "rm", INTERNAL_NETWORK],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def agent_image():  # type: ignore[return]
    """Ensure the agent image is available with the test tag."""
    # Tag the existing latest image as :test (already done by the build step).
    subprocess.run(
        ["docker", "tag", "agent-runtime:latest", f"agent-runtime:{AGENT_IMAGE_TAG}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return AGENT_IMAGE_TAG


@pytest.fixture(scope="session")
def stub_llm(docker_network: str):  # type: ignore[return]
    """Start the control-plane stub Anthropic server on the test internal network.

    Listens on port 8080 inside the container; reachable as
    http://stub-llm-test:8080 from other containers on the same network.
    Also binds to an ephemeral host port so the test process can query
    /_test/last_auth_header to verify decrypted credentials arrived at the LLM.
    Scripts a 2-turn conversation: write_file(out.txt) → done({"value": 42}).

    Yields a tuple (container_url, host_url).
    """
    import socket

    subprocess.run(
        ["docker", "rm", "-f", STUB_LLM_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Pick a free ephemeral port on the host so the test process can reach the
    # stub LLM directly (needed to query /_test/last_auth_header).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        host_port = _s.getsockname()[1]
    _run([
        "docker", "run", "-d", "--name", STUB_LLM_NAME,
        "--network", docker_network,
        "-p", f"127.0.0.1:{host_port}:8080",
        "agent-runtime-stub-llm:test",
    ])
    yield f"http://{STUB_LLM_NAME}:8080", f"http://127.0.0.1:{host_port}"
    subprocess.run(
        ["docker", "rm", "-f", STUB_LLM_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def stub_llm_host_url(stub_llm: tuple) -> str:  # type: ignore[return]
    """Return the host-accessible URL for the stub LLM server.

    Used by the credential-attach integration test to query
    ``/_test/last_auth_header`` and verify that the decrypted credential
    arrived at the LLM without being persisted in the DB.
    """
    _container_url, host_url = stub_llm
    return host_url


@pytest.fixture(scope="session")
def pg():  # type: ignore[return]
    """Start a throwaway Postgres container for the test session."""
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer("postgres:16") as p:
        # asyncpg URL form required by alembic env.py and make_engine.
        raw_url = p.get_connection_url()
        if "+psycopg2" in raw_url:
            async_url = raw_url.replace("+psycopg2", "+asyncpg")
        elif raw_url.startswith("postgresql://"):
            async_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            async_url = raw_url
        yield async_url


@pytest_asyncio.fixture
async def migrated_db(pg: str) -> str:
    """Apply alembic migrations to the testcontainer Postgres."""
    import asyncio

    ini_path = os.path.join(_CP_DIR, "alembic.ini")
    env = {
        **os.environ,
        "DATABASE_URL": pg,
        # Ensure PYTHONPATH includes the control_plane package root.
        "PYTHONPATH": _CP_DIR,
    }

    def _run_alembic() -> None:
        subprocess.run(
            [_VENV_ALEMBIC, "-c", ini_path, "upgrade", "head"],
            check=True,
            env=env,
            cwd=_CP_DIR,
        )

    await asyncio.to_thread(_run_alembic)
    return pg


@pytest_asyncio.fixture
async def app_settings(migrated_db: str, docker_network: str, agent_image: str, stub_llm: tuple):  # type: ignore[return]
    from control_plane.config import Settings

    # stub_llm is (container_url, host_url) — agents see the container URL;
    # the test process can query the host URL for header introspection.
    stub_llm_container_url, _stub_llm_host_url = stub_llm

    return Settings(
        database_url=migrated_db,
        seed_tenant_id="ten_seed",
        seed_api_key="tk_live_seedkey",
        seed_llm_api_key="stub-key",
        agent_image_tag=agent_image,
        internal_network=docker_network,
        readyz_timeout_seconds=60,
        shim_port=8080,
        # Bind the shim port to an ephemeral host port so the control-plane
        # process (running on the macOS host, outside Docker) can reach it.
        # On Linux CI the container IP is routable and this can be False.
        bind_shim_port_to_host=True,
        agent_extra_env={
            "ANTHROPIC_BASE_URL": stub_llm_container_url,
            # Vanilla multi-provider: route the OpenAI and opencode-go paths to
            # the same stub. OpenAICompatClient appends /chat/completions to its
            # base (hence the /v1 here); AnthropicClient appends /v1/messages.
            "OPENAI_BASE_URL": f"{stub_llm_container_url}/v1",
            "OPENCODE_GO_BASE_URL": stub_llm_container_url,
            # Built-in web tools hit the stub instead of real searxng/websites.
            "SEARCH_PROVIDER_URL": stub_llm_container_url,
            # Disable the egress proxy inside the test container — it doesn't
            # exist on the test network and httpx would fail connecting to it.
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "NO_PROXY": "*",
            "no_proxy": "*",
        },
    )


async def _seed_credential(factory: object, tenant_id: str, api_key: str) -> None:
    """Reset *tenant_id* to a single canonical 'anthropic' api_key credential.

    Uses the test master key so load_key_from_env() can decrypt it at submit time.
    Called after apply_seed so the tenant row already exists.

    Per-test credential isolation: the Postgres container is session-scoped and
    the seed tenant is shared, so credential-creating tests (e.g. the OpenAI/
    Anthropic OAuth flows) would otherwise leave rows on the seed tenant that
    bleed into later tests — e.g. a leftover OpenAI credential makes the
    models-endpoint badge test see OpenAI as 'available'. We therefore delete
    ALL of the tenant's credentials (every provider + auth_method) before
    inserting the canonical anthropic key, mirroring the limits reset in
    seeded_app so each test starts from a known credential slate.
    """
    import sqlalchemy as sa

    from control_plane.credentials_service import build_credential_row
    from control_plane.tables import credentials

    row = build_credential_row(
        tenant_id=tenant_id,
        provider="anthropic",
        api_key=api_key,
        created_by=None,
        master_key=_TEST_MASTER_KEY,
    )
    async with factory() as s:  # type: ignore[attr-defined]
        # Clear EVERY credential for the tenant (not just anthropic) so leftover
        # rows from other tests can't bleed in, then insert the canonical key.
        await s.execute(
            sa.delete(credentials).where(credentials.c.tenant_id == tenant_id)
        )
        await s.execute(sa.insert(credentials).values(**row))
        await s.commit()


def _wire_lifecycle_state(app: object, factory: object, settings: object) -> object:
    """Wire docker_client + shim onto app.state directly.

    ASGITransport does not run the FastAPI lifespan, so the lifecycle ops
    (pause/resume/recover/destroy) — which reach Docker via app.state — would
    otherwise see ``docker_client is None``. Mirrors the production startup in
    control_plane.app. Background sweeps are NOT started (no lifespan), so this
    is purely additive. Returns the client so the fixture can close it.
    """
    import docker as _docker

    from control_plane.app import _ContainerShimDispatcher

    try:
        client = _docker.from_env()
    except Exception:  # noqa: BLE001
        client = None
    app.state.docker_client = client  # type: ignore[attr-defined]
    app.state.shim = (  # type: ignore[attr-defined]
        _ContainerShimDispatcher(factory, settings.shim_port)
        if client is not None
        else None
    )
    return client


@pytest_asyncio.fixture
async def seeded_app(app_settings):  # type: ignore[return]
    from sqlalchemy import update

    from control_plane.app import create_app
    from control_plane.db import make_engine, make_session_factory
    from control_plane.models_db import tenants
    from control_plane.seed import SEED_TENANT_LIMITS, apply_seed

    engine = make_engine(app_settings)
    factory = make_session_factory(engine)
    async with factory() as s:
        await apply_seed(s, app_settings)
        # Always reset tenant limits to the canonical seed values so that
        # tests which modify limits (e.g. cap tests) do not bleed state into
        # subsequent fixtures sharing the same Postgres container.
        await s.execute(
            update(tenants)
            .where(tenants.c.id == app_settings.seed_tenant_id)
            .values(limits=SEED_TENANT_LIMITS)
        )
        await s.commit()
    # Store an encrypted anthropic credential for the seed tenant (Task 16).
    await _seed_credential(factory, app_settings.seed_tenant_id, app_settings.seed_llm_api_key)
    app = create_app(app_settings)
    docker_client = _wire_lifecycle_state(app, factory, app_settings)
    yield app
    if docker_client is not None:
        docker_client.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_app_cap1(app_settings):  # type: ignore[return]
    """Same as seeded_app but with max_concurrent_tasks_per_container = 1.

    This makes the shim's worker pool size 1, so the second concurrent task
    is immediately rejected with 429.
    """
    from sqlalchemy import update

    from control_plane.app import create_app
    from control_plane.db import make_engine, make_session_factory
    from control_plane.models_db import tenants
    from control_plane.seed import SEED_TENANT_LIMITS, apply_seed

    engine = make_engine(app_settings)
    factory = make_session_factory(engine)
    async with factory() as s:
        await apply_seed(s, app_settings)
        new_limits = dict(SEED_TENANT_LIMITS)
        new_limits["max_concurrent_tasks_per_container"] = 1
        await s.execute(
            update(tenants)
            .where(tenants.c.id == app_settings.seed_tenant_id)
            .values(limits=new_limits)
        )
        await s.commit()
    # Store an encrypted anthropic credential for the seed tenant (Task 16).
    await _seed_credential(factory, app_settings.seed_tenant_id, app_settings.seed_llm_api_key)
    app = create_app(app_settings)
    docker_client = _wire_lifecycle_state(app, factory, app_settings)
    yield app
    if docker_client is not None:
        docker_client.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def app_with_admin_key(  # type: ignore[return]
    migrated_db: str, docker_network: str, agent_image: str, stub_llm: tuple
) -> object:
    """Like seeded_app but also sets admin_api_key so /admin/v1/tenants works.

    Used by the auth-flow and credential-attach integration tests which bootstrap
    their own fresh tenants (rather than using the pre-seeded one).
    """
    from control_plane.app import create_app
    from control_plane.config import Settings
    from control_plane.db import make_engine, make_session_factory
    from control_plane.seed import apply_seed

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
        await s.commit()
    app = create_app(settings)
    docker_client = _wire_lifecycle_state(app, factory, settings)
    yield app
    if docker_client is not None:
        docker_client.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def app_member_cap2(  # type: ignore[return]
    migrated_db: str, docker_network: str, agent_image: str, stub_llm: tuple
) -> object:
    """Like app_with_admin_key but caps regular users at 2 owned workspaces."""
    from control_plane.app import create_app
    from control_plane.config import Settings
    from control_plane.db import make_engine, make_session_factory
    from control_plane.seed import apply_seed

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
        max_owned_tenants_per_user=2,
        agent_extra_env={
            "ANTHROPIC_BASE_URL": stub_llm_container_url,
            "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
            "NO_PROXY": "*", "no_proxy": "*",
        },
    )
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    async with factory() as s:
        await apply_seed(s, settings)
        await s.commit()
    app = create_app(settings)
    docker_client = _wire_lifecycle_state(app, factory, settings)
    yield app
    if docker_client is not None:
        docker_client.close()
    await engine.dispose()

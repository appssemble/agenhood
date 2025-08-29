"""Networking chokepoint integration tests (spec §8.1).

These prove that an agent-shaped container on the internal-only network has NO
path to the internet except the egress proxy, and that the proxy enforces the
egress policy. Real docker required; skips cleanly without a daemon.

Docker Desktop / curl note: curl bypasses HTTP_PROXY for link-local and
RFC1918 addresses (those it considers "local"). To force curl to send ALL
requests through the proxy we use the explicit ``-x <proxy_url>`` flag
instead of the HTTP_PROXY env var. This is the correct real-world behaviour
too: agents must set the proxy explicitly, not rely on env-var bypass logic.
"""
import os as _os
import time

import pytest

docker = pytest.importorskip("docker")

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


skip_no_docker = pytest.mark.skipif(
    not _docker_available(), reason="docker daemon not available"
)

PROXY_ENV = {"EGRESS_DENYLIST": "blocked.test.invalid"}
PROXY_CONTAINER_NAME = "art-test-proxy"
PROXY_URL = f"http://{PROXY_CONTAINER_NAME}:8888"
ALLOWED_HOST = "example.com"           # stable public host
PROBE_IMAGE = "curlimages/curl:8.7.1"  # tiny, has curl; pulled once

# Compute the path to images/egress-proxy relative to the repo root.
# This file is at services/control_plane/tests/test_networking_integration.py,
# so the repo root is three service-path levels up from the tests/ dir.
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
_REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_THIS_DIR)))
_PROXY_BUILD_PATH = _os.path.join(_REPO_ROOT, "images", "egress-proxy")


@pytest.fixture(scope="module")
def env():  # type: ignore[return]
    client = docker.from_env()
    # Build the proxy image from the Dockerfile.
    client.images.build(path=_PROXY_BUILD_PATH,
                        tag="agent-runtime/egress-proxy:test", rm=True)
    client.images.pull(PROBE_IMAGE)

    internal = client.networks.create(
        "art-test-internal", driver="bridge", internal=True)
    egress = client.networks.create(
        "art-test-egress", driver="bridge", internal=False)

    proxy = client.containers.run(
        "agent-runtime/egress-proxy:test",
        name=PROXY_CONTAINER_NAME, detach=True,
        environment=PROXY_ENV, network="art-test-internal",
    )
    egress.connect(proxy)   # second NIC: the proxy alone reaches upstream
    time.sleep(1.5)         # let the proxy bind :8888

    try:
        yield {"client": client, "proxy": proxy,
               "internal": internal, "egress": egress}
    finally:
        for name in (PROXY_CONTAINER_NAME,):
            try:
                client.containers.get(name).remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        for net in (internal, egress):
            try:
                net.remove()
            except Exception:  # noqa: BLE001
                pass


def _probe(
    client,
    cmd: list[str],
    *,
    proxy_url: str | None = None,
) -> tuple[int, str]:
    """Run a one-shot probe container attached ONLY to the internal network.

    When *proxy_url* is provided, the command list should already contain
    ``-x <proxy_url>`` flags (explicit proxy, avoids curl's no-proxy bypass
    for link-local and RFC1918 addresses when using the HTTP_PROXY env var).
    """
    container = client.containers.create(
        PROBE_IMAGE, command=cmd,
        network="art-test-internal",
    )
    try:
        container.start()
        result = container.wait(timeout=40)
        logs = container.logs().decode("utf-8", "replace")
        return result["StatusCode"], logs
    finally:
        container.remove(force=True)


@skip_no_docker
def test_direct_egress_without_proxy_fails(env):
    """(a) Direct outbound request on the internal-only network FAILS.

    No proxy set; the container is on the internal bridge which has no
    default gateway to the public internet. curl must time out / fail.
    """
    code, logs = _probe(
        env["client"],
        ["-sS", "--max-time", "8", f"http://{ALLOWED_HOST}/"],
    )
    assert code != 0, f"expected failure but curl succeeded: {logs}"


@skip_no_docker
def test_proxy_blocks_metadata_endpoint(env):
    """(b) Through the proxy, http://169.254.169.254/ is BLOCKED (403).

    169.254.0.0/16 is link-local; the proxy classifier returns link_local.
    We use ``-x`` (explicit proxy) because curl's HTTP_PROXY env var skips
    the proxy for link-local addresses — ``-x`` forces ALL traffic through
    the proxy regardless of the destination address class.
    curl exits 0 (it received an HTTP response from the proxy) but the
    status code written to stdout by ``-w %{http_code}`` must be 403.
    """
    code, logs = _probe(
        env["client"],
        ["-sS", "-x", PROXY_URL, "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "8", "http://169.254.169.254/latest/meta-data/"],
    )
    assert "403" in logs, f"expected 403 from proxy, got: code={code} logs={logs!r}"


@skip_no_docker
def test_proxy_blocks_rfc1918(env):
    """(c) Through the proxy, an RFC1918 address is BLOCKED (403).

    10.0.0.1 is in the 10/8 private range; the proxy classifier returns
    private_range and the proxy replies 403 without attempting a connection.
    We use ``-x`` (explicit proxy) because curl's HTTP_PROXY env var skips
    the proxy for RFC1918 addresses.
    """
    code, logs = _probe(
        env["client"],
        ["-sS", "-x", PROXY_URL, "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "8", "http://10.0.0.1/"],
    )
    assert "403" in logs, f"expected 403 from proxy, got: code={code} logs={logs!r}"


@skip_no_docker
def test_proxy_allows_public_host_and_logs_it(env):
    """(d) Through the proxy, an allowed public host SUCCEEDS and appears in the log.

    example.com resolves to a public IP; the proxy classifies it as allowed,
    tunnels the CONNECT for HTTPS, and writes a JSON log line with
    ``"decision": "allow"`` and the host name.
    """
    code, logs = _probe(
        env["client"],
        ["-sS", "-x", PROXY_URL, "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "20", f"https://{ALLOWED_HOST}/"],
    )
    assert "200" in logs or "301" in logs or "302" in logs, (
        f"expected 200/30x from proxy, got: code={code} logs={logs!r}"
    )
    # The allow decision must appear in the proxy's structured log.
    time.sleep(0.5)
    proxy_logs = env["proxy"].logs().decode("utf-8", "replace")
    assert ALLOWED_HOST in proxy_logs, (
        f"{ALLOWED_HOST!r} not found in proxy logs: {proxy_logs!r}"
    )
    assert '"decision": "allow"' in proxy_logs or '"decision":"allow"' in proxy_logs, (
        f'"decision": "allow" not found in proxy logs: {proxy_logs!r}'
    )


# --------------------------------------------------------------------------
# opencode-through-the-proxy integration test (spec §3.5.2 + §8.1).
#
# The opencode driver shells out to a Bun-based binary whose `fetch()` reaches
# the model over an HTTPS CONNECT tunnel spliced by the egress proxy. Two proxy
# bugs used to break exactly that path (a malformed CONNECT response Bun
# mishandled, and a half-close that truncated the tunnel). This test is the
# end-to-end regression guard: it runs a real opencode agent container on the
# internal-ONLY network — which has NO internet gateway — so the agent's *only*
# possible route to the model is HTTPS_PROXY -> the proxy's CONNECT splice. If
# the splice is broken, opencode cannot reach the model and the run fails. A
# successful keyless free-model reply is therefore proof the splice path works.
# --------------------------------------------------------------------------

# The agent image carries the opencode binary; default to the locally built tag.
AGENT_IMAGE = _os.environ.get("AGENT_IMAGE", "agent-runtime:latest")
FREE_MODEL = "opencode/deepseek-v4-flash-free"  # keyless "Zen" model — no API key
_XDG_BASE = "/workspace/.agent-runtime/opencode"


def _agent_image_present(client) -> bool:
    try:
        client.images.get(AGENT_IMAGE)
        return True
    except Exception:  # noqa: BLE001
        return False


@skip_no_docker
def test_opencode_reaches_free_model_only_through_the_proxy(env):
    """(e) A real opencode agent completes a free-model task via the proxy splice.

    The container is attached to the internal-only network (no default route to
    the internet), with HTTP(S)_PROXY pointed at the egress proxy exactly as the
    control plane provisions production agents. The opencode binary's Bun
    ``fetch`` must therefore tunnel to the model through the proxy's CONNECT
    splice. We assert the process exits 0 and emitted a ``type:"text"`` assistant
    event — which can only happen if the model reply came back through the
    spliced tunnel — and that the proxy logged a fresh ``allow`` CONNECT.
    """
    client = env["client"]
    if not _agent_image_present(client):
        pytest.skip(
            f"agent image {AGENT_IMAGE!r} not built; run `make -C images/agent image`"
        )

    # Mirror the production agent env (provision.py): proxy on, XDG redirected to
    # the writable workspace because the image's $HOME is not process-writable.
    environment = {
        "HTTP_PROXY": PROXY_URL,
        "HTTPS_PROXY": PROXY_URL,
        "NO_PROXY": "localhost,127.0.0.1",
        "XDG_DATA_HOME": f"{_XDG_BASE}/data",
        "XDG_CONFIG_HOME": f"{_XDG_BASE}/config",
        "XDG_CACHE_HOME": f"{_XDG_BASE}/cache",
        "HOME": _XDG_BASE,
    }
    # Replicate the driver's exact opencode 1.x invocation (build_command).
    script = (
        'set -e; mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$HOME"; '
        "exec opencode run --dir /workspace --format json "
        f"-m {FREE_MODEL} --dangerously-skip-permissions "
        '-- "Reply with exactly one word: PONG"'
    )

    # Snapshot proxy logs so we can prove THIS run produced a fresh allow line.
    proxy_log_before = env["proxy"].logs().decode("utf-8", "replace")

    container = client.containers.create(
        AGENT_IMAGE,
        entrypoint=["bash", "-lc"],
        command=[script],
        environment=environment,
        network="art-test-internal",
    )
    try:
        container.start()
        result = container.wait(timeout=180)
        logs = container.logs().decode("utf-8", "replace")
        code = result["StatusCode"]
    finally:
        container.remove(force=True)

    # The agent had no route to the internet except the proxy; a 0 exit means
    # the CONNECT splice carried opencode's model traffic both ways.
    assert code == 0, f"opencode failed through the proxy: code={code}\nlogs={logs}"
    # An assistant text event only exists if the model actually replied.
    assert '"type":"text"' in logs or '"type": "text"' in logs, (
        f"no opencode text event — model never answered through the proxy:\n{logs}"
    )
    # And the proxy itself must have logged a fresh allow CONNECT for this run.
    time.sleep(0.5)
    proxy_log_after = env["proxy"].logs().decode("utf-8", "replace")
    fresh = proxy_log_after[len(proxy_log_before):]
    assert '"decision": "allow"' in fresh or '"decision":"allow"' in fresh, (
        f"no fresh allow decision in proxy log for the opencode run:\n{fresh!r}"
    )


# --------------------------------------------------------------------------
# Traefik routing integration test (spec §10): same-origin path routing,
# SSE streaming, cookie preserved, no CORS. Uses stand-in app containers wired
# with the production labels so it tests THIS unit's routing, not Units 2/6 apps.
# --------------------------------------------------------------------------

PUBLIC_HOST = "agent.test.local"

_SSE_APP = "\n".join([
    "import http.server, socketserver",
    "class H(http.server.BaseHTTPRequestHandler):",
    "    def do_GET(self):",
    "        if self.path == '/v1/healthz':",
    "            self.send_response(200)",
    "            self.send_header('Content-Type','application/json')",
    "            self.end_headers()",
    "            self.wfile.write(b'{\"status\":\"ok\"}'); return",
    "        if self.path.startswith('/v1/stream'):",
    "            self.send_response(200)",
    "            self.send_header('Content-Type','text/event-stream')",
    "            cookie = self.headers.get('Cookie','')",
    "            self.send_header('X-Saw-Cookie', cookie)",
    "            self.end_headers()",
    "            for i in range(3):",
    "                self.wfile.write(('data: tick %d\\n\\n'%i).encode())",
    "                self.wfile.flush()",
    "            return",
    "        self.send_response(404); self.end_headers()",
    "    def log_message(self,*a): pass",
    "socketserver.TCPServer(('0.0.0.0',8443), H).serve_forever()",
])

_SPA_APP = "\n".join([
    "import http.server, socketserver",
    "class H(http.server.BaseHTTPRequestHandler):",
    "    def do_GET(self):",
    "        self.send_response(200)",
    "        self.send_header('Content-Type','text/html')",
    "        self.end_headers()",
    "        self.wfile.write(b'<html>console SPA</html>')",
    "    def log_message(self,*a): pass",
    "socketserver.TCPServer(('0.0.0.0',80), H).serve_forever()",
])


_TRAEFIK_CONTAINER_NAMES = ("art-test-api", "art-test-spa", "art-test-traefik")
_TRAEFIK_NETWORK_NAME = "art-test-edge"


def _traefik_stack_cleanup(client) -> None:
    """Remove any leftover resources from a previous (possibly crashed) run."""
    for name in _TRAEFIK_CONTAINER_NAMES:
        try:
            client.containers.get(name).remove(force=True)
        except Exception:  # noqa: BLE001
            pass
    for net in client.networks.list(names=[_TRAEFIK_NETWORK_NAME]):
        try:
            net.remove()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(scope="module")
def traefik_stack():
    client = docker.from_env()
    _traefik_stack_cleanup(client)
    client.images.pull("python:3.12-slim")
    client.images.pull("traefik:v3")
    net = client.networks.create(_TRAEFIK_NETWORK_NAME, driver="bridge")
    containers = []

    def run_app(name, code, label_lines):
        c = client.containers.run(
            "python:3.12-slim", name=name, detach=True,
            network=_TRAEFIK_NETWORK_NAME,
            command=["python", "-c", code],
            labels={k: v for k, v in (lbl.split("=", 1) for lbl in label_lines)},
        )
        containers.append(c)
        return c

    run_app("art-test-api", _SSE_APP, [
        "traefik.enable=true",
        f"traefik.http.routers.api.rule=Host(`{PUBLIC_HOST}`) && PathPrefix(`/v1`)",
        "traefik.http.routers.api.priority=10",
        "traefik.http.routers.api.entrypoints=web",
        "traefik.http.services.api.loadbalancer.server.port=8443",
    ])
    run_app("art-test-spa", _SPA_APP, [
        "traefik.enable=true",
        f"traefik.http.routers.spa.rule=Host(`{PUBLIC_HOST}`)",
        "traefik.http.routers.spa.priority=1",
        "traefik.http.routers.spa.entrypoints=web",
        "traefik.http.services.spa.loadbalancer.server.port=80",
    ])

    traefik = client.containers.run(
        "traefik:v3", name="art-test-traefik", detach=True,
        network=_TRAEFIK_NETWORK_NAME,
        command=[
            "--entrypoints.web.address=:80",
            "--providers.docker=true",
            "--providers.docker.exposedbydefault=false",
        ],
        ports={"80/tcp": ("127.0.0.1", 0)},
        volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "ro"}},
    )
    containers.append(traefik)
    traefik.reload()
    host_port = int(traefik.ports["80/tcp"][0]["HostPort"])
    time.sleep(3)  # let traefik discover labels

    try:
        yield host_port
    finally:
        for c in containers:
            try:
                c.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            net.remove()
        except Exception:  # noqa: BLE001
            pass


def _http(host_port, path, headers=None):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", host_port, timeout=10)
    h = {"Host": PUBLIC_HOST}
    if headers:
        h.update(headers)
    conn.request("GET", path, headers=h)
    resp = conn.getresponse()
    body = resp.read()
    status = resp.status
    saw_cookie = resp.getheader("X-Saw-Cookie")
    conn.close()
    return status, body, saw_cookie


@skip_no_docker
def test_traefik_routes_root_to_console(traefik_stack):
    status, body, _ = _http(traefik_stack, "/")
    assert status == 200
    assert b"console SPA" in body


@skip_no_docker
def test_traefik_routes_v1_healthz_to_control_plane(traefik_stack):
    status, body, _ = _http(traefik_stack, "/v1/healthz")
    assert status == 200
    assert b'"status":"ok"' in body


@skip_no_docker
def test_traefik_streams_sse_with_cookie_preserved(traefik_stack):
    status, body, saw_cookie = _http(
        traefik_stack, "/v1/stream",
        headers={"Cookie": "session=abc123", "Accept": "text/event-stream"},
    )
    assert status == 200
    # SSE frames streamed through (same-origin, no CORS gymnastics needed).
    assert b"data: tick 0" in body and b"data: tick 2" in body
    # The control plane saw the session cookie => cookie preserved end-to-end.
    assert saw_cookie == "session=abc123"

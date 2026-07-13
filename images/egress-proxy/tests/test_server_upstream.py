"""Chaining through an upstream proxy (e.g. Webshare's rotating endpoint).

A stub upstream proxy stands in for Webshare: it speaks CONNECT and absolute-URI
plain HTTP, records what it was asked for, and never touches the network. A
separate loopback origin server stands in for "the public internet" so the
direct path can be exercised too — socket.create_connection is redirected the
same way test_server_relay.py does it.
"""
import http.client
import ipaddress
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from proxy.policy import EgressPolicy, UpstreamPolicy
from proxy.server import ProxyServer

ORIGIN_BODY = b"DIRECT_FROM_ORIGIN"
VIA_UPSTREAM_BODY = b"VIA_UPSTREAM_PROXY"


# ---- stub upstream proxy (stands in for Webshare) --------------------------

class _StubUpstreamHandler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(65536).decode("latin-1").strip()
        headers = {}
        header_lines = []
        while True:
            raw = self.rfile.readline(65536).decode("latin-1")
            if raw in ("\r\n", "\n", ""):
                break
            header_lines.append(raw.rstrip("\r\n"))
            k, _, v = raw.partition(":")
            headers[k.strip().lower()] = v.strip()
        self.server.requests.append((line, headers))
        self.server.header_lines.append(header_lines)

        if line.startswith("CONNECT"):
            if self.server.connect_status != 200:
                self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                self.wfile.flush()
                return
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            self._echo()
            return

        body = VIA_UPSTREAM_BODY
        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
        self.wfile.write(b"Content-Type: text/plain\r\n")
        self.wfile.write(f"Content-Length: {len(body)}\r\n".encode())
        self.wfile.write(b"\r\n")
        self.wfile.write(body)
        self.wfile.flush()

    def _echo(self):
        """Echo tunnelled bytes back so the test can prove the splice works."""
        while True:
            data = self.connection.recv(4096)
            if not data:
                return
            self.connection.sendall(data)


class _StubUpstream(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, connect_status=200):
        self.requests = []
        self.header_lines = []
        self.connect_status = connect_status
        super().__init__(("127.0.0.1", 0), _StubUpstreamHandler)


@pytest.fixture
def stub_upstream():
    srv = _StubUpstream()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


# ---- loopback origin (stands in for the real public internet) --------------

class _Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(ORIGIN_BODY)))
        self.end_headers()
        self.wfile.write(ORIGIN_BODY)

    def log_message(self, *a):
        pass


@pytest.fixture
def origin():
    srv = HTTPServer(("127.0.0.1", 0), _Origin)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture
def redirect_direct_dials(origin, monkeypatch):
    """Send any non-loopback dial (the DIRECT path) to the loopback origin."""
    real = socket.create_connection

    def fake(addr, timeout=None, source_address=None):
        try:
            if ipaddress.ip_address(addr[0]).is_loopback:
                return real(addr, timeout, source_address)
        except ValueError:
            pass
        return real(("127.0.0.1", origin), timeout)

    monkeypatch.setattr("socket.create_connection", fake)


def _upstream_policy(stub, mode="all", hosts=(), *, creds=True):
    return UpstreamPolicy(
        host="127.0.0.1",
        port=stub.server_address[1],
        username="user-rotate" if creds else None,
        password="secret" if creds else None,
        mode=mode,
        hosts=frozenset(hosts),
    )


def _start_proxy(upstream, denylist=frozenset({"blocked.example"})):
    server = ProxyServer(
        ("127.0.0.1", 0),
        EgressPolicy(denylist=denylist),
        resolve=lambda h: {"private.example": ["10.0.0.1"]}.get(h, ["93.184.216.34"]),
        upstream=upstream,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    return server


def _proxy_get(port, url):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", url)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _proxy_connect(port, authority, payload=b"ping"):
    """CONNECT through our proxy, then send bytes through the tunnel."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
    status_line = b""
    while not status_line.endswith(b"\r\n\r\n"):
        chunk = s.recv(1)
        if not chunk:
            break
        status_line += chunk
    status = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0
    echoed = b""
    if status == 200:
        s.sendall(payload)
        echoed = s.recv(4096)
    s.close()
    return status, echoed


# ---- plain HTTP through the upstream ---------------------------------------

def test_plain_http_chains_through_upstream_in_absolute_uri_form(
    stub_upstream,
    redirect_direct_dials,
):
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        status, body = _proxy_get(server.server_address[1], "http://target.example/path?q=1")
    finally:
        server.shutdown()
    assert status == 200
    assert body == VIA_UPSTREAM_BODY          # served by the upstream, not the origin
    line, headers = stub_upstream.requests[-1]
    assert line == "GET http://target.example/path?q=1 HTTP/1.1"
    assert headers["proxy-authorization"] == "Basic dXNlci1yb3RhdGU6c2VjcmV0"


def test_plain_http_sends_exactly_one_host_header(stub_upstream, redirect_direct_dials):
    # A duplicate Host header (a lowercased copy of the client's alongside our
    # canonical one) makes strict upstreams reject the request with 400.
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        _proxy_get(server.server_address[1], "http://target.example/")
    finally:
        server.shutdown()
    host_lines = [ln for ln in stub_upstream.header_lines[-1]
                  if ln.split(":", 1)[0].strip().lower() == "host"]
    assert host_lines == ["Host: target.example"]


def test_plain_http_omits_auth_header_when_upstream_has_no_credentials(
    stub_upstream,
    redirect_direct_dials,
):
    server = _start_proxy(_upstream_policy(stub_upstream, creds=False))
    try:
        _proxy_get(server.server_address[1], "http://target.example/")
    finally:
        server.shutdown()
    _line, headers = stub_upstream.requests[-1]
    assert "proxy-authorization" not in headers


# ---- CONNECT through the upstream ------------------------------------------

def test_connect_chains_through_upstream_and_splices(stub_upstream, redirect_direct_dials):
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        status, echoed = _proxy_connect(server.server_address[1], "target.example:443")
    finally:
        server.shutdown()
    assert status == 200
    assert echoed == b"ping"                  # tunnel spliced end to end
    line, headers = stub_upstream.requests[-1]
    assert line == "CONNECT target.example:443 HTTP/1.1"
    assert headers["proxy-authorization"] == "Basic dXNlci1yb3RhdGU6c2VjcmV0"


# ---- routing: exclude / include --------------------------------------------

def test_excluded_host_goes_direct_and_never_touches_the_upstream(
    stub_upstream,
    redirect_direct_dials,
):
    policy = _upstream_policy(stub_upstream, mode="exclude", hosts={"api.anthropic.com"})
    server = _start_proxy(policy)
    try:
        status, body = _proxy_get(server.server_address[1], "http://api.anthropic.com/v1/messages")
    finally:
        server.shutdown()
    assert status == 200
    assert body == ORIGIN_BODY                # direct to the origin
    assert stub_upstream.requests == []       # upstream untouched


def test_non_excluded_host_still_chains_in_exclude_mode(stub_upstream, redirect_direct_dials):
    policy = _upstream_policy(stub_upstream, mode="exclude", hosts={"api.anthropic.com"})
    server = _start_proxy(policy)
    try:
        _status, body = _proxy_get(server.server_address[1], "http://linkedin.com/in/x")
    finally:
        server.shutdown()
    assert body == VIA_UPSTREAM_BODY
    assert len(stub_upstream.requests) == 1


def test_non_included_host_goes_direct_in_include_mode(stub_upstream, redirect_direct_dials):
    policy = _upstream_policy(stub_upstream, mode="include", hosts={"linkedin.com"})
    server = _start_proxy(policy)
    try:
        _status, body = _proxy_get(server.server_address[1], "http://api.anthropic.com/v1/messages")
    finally:
        server.shutdown()
    assert body == ORIGIN_BODY
    assert stub_upstream.requests == []


def test_included_host_chains_in_include_mode(stub_upstream, redirect_direct_dials):
    policy = _upstream_policy(stub_upstream, mode="include", hosts={"linkedin.com"})
    server = _start_proxy(policy)
    try:
        _status, body = _proxy_get(server.server_address[1], "http://www.linkedin.com/in/x")
    finally:
        server.shutdown()
    assert body == VIA_UPSTREAM_BODY          # subdomain matches via suffix rule
    assert len(stub_upstream.requests) == 1


# ---- the sandbox still wins over routing -----------------------------------

def test_denylisted_host_is_blocked_before_any_upstream_connection(
    stub_upstream,
    redirect_direct_dials,
):
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        status, _ = _proxy_get(server.server_address[1], "http://blocked.example/")
    finally:
        server.shutdown()
    assert status == 403
    assert stub_upstream.requests == []


def test_private_range_host_is_blocked_before_any_upstream_connection(
    stub_upstream,
    redirect_direct_dials,
):
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        status, _ = _proxy_get(server.server_address[1], "http://private.example/")
    finally:
        server.shutdown()
    assert status == 403
    assert stub_upstream.requests == []


def test_connect_to_denylisted_host_is_blocked_before_any_upstream_connection(
    stub_upstream,
    redirect_direct_dials,
):
    server = _start_proxy(_upstream_policy(stub_upstream))
    try:
        status, _ = _proxy_connect(server.server_address[1], "blocked.example:443")
    finally:
        server.shutdown()
    assert status == 403
    assert stub_upstream.requests == []


# ---- failing closed --------------------------------------------------------

def test_connect_is_502_when_upstream_refuses_the_tunnel(redirect_direct_dials):
    stub = _StubUpstream(connect_status=403)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    server = _start_proxy(_upstream_policy(stub))
    try:
        status, _ = _proxy_connect(server.server_address[1], "target.example:443")
    finally:
        server.shutdown()
        stub.shutdown()
    assert status == 502          # no silent fallback to a direct connection


def test_connect_is_502_when_upstream_is_unreachable(redirect_direct_dials):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()                  # nothing is listening there now

    policy = UpstreamPolicy(
        host="127.0.0.1", port=dead_port, username=None, password=None,
        mode="all", hosts=frozenset(),
    )
    server = _start_proxy(policy)
    try:
        status, _ = _proxy_connect(server.server_address[1], "target.example:443")
    finally:
        server.shutdown()
    assert status == 502


def test_plain_http_is_502_when_upstream_is_unreachable(redirect_direct_dials):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()

    policy = UpstreamPolicy(
        host="127.0.0.1", port=dead_port, username=None, password=None,
        mode="all", hosts=frozenset(),
    )
    server = _start_proxy(policy)
    try:
        status, body = _proxy_get(server.server_address[1], "http://target.example/")
    finally:
        server.shutdown()
    assert status == 502
    assert body != ORIGIN_BODY    # it did NOT quietly fall back to a direct dial


# ---- opt-in fallback to direct ---------------------------------------------

def _dead_upstream(fallback_direct):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()                  # nothing is listening there now
    return UpstreamPolicy(
        host="127.0.0.1", port=dead_port, username=None, password=None,
        mode="all", hosts=frozenset(), fallback_direct=fallback_direct,
    )


def _proxy_connect_then_get(port, authority):
    """CONNECT via our proxy, then drive a plain GET through the tunnel."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
    status_line = b""
    while not status_line.endswith(b"\r\n\r\n"):
        chunk = s.recv(1)
        if not chunk:
            break
        status_line += chunk
    status = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0
    body = b""
    if status == 200:
        s.sendall(b"GET / HTTP/1.1\r\nHost: target.example\r\nConnection: close\r\n\r\n")
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            body += chunk
    s.close()
    return status, body


def test_plain_http_falls_back_to_direct_when_enabled_and_upstream_down(redirect_direct_dials):
    server = _start_proxy(_dead_upstream(fallback_direct=True))
    try:
        status, body = _proxy_get(server.server_address[1], "http://target.example/")
    finally:
        server.shutdown()
    assert status == 200
    assert body == ORIGIN_BODY    # served directly by the origin after upstream failed


def test_connect_falls_back_to_direct_when_enabled_and_upstream_down(redirect_direct_dials):
    server = _start_proxy(_dead_upstream(fallback_direct=True))
    try:
        status, body = _proxy_connect_then_get(server.server_address[1], "target.example:443")
    finally:
        server.shutdown()
    assert status == 200          # tunnel established against the origin directly
    assert ORIGIN_BODY in body


def test_fallback_off_by_default_still_502(redirect_direct_dials):
    # Same dead upstream, fallback NOT enabled -> fail closed, no direct dial.
    server = _start_proxy(_dead_upstream(fallback_direct=False))
    try:
        status, body = _proxy_get(server.server_address[1], "http://target.example/")
    finally:
        server.shutdown()
    assert status == 502
    assert body != ORIGIN_BODY


def test_fallback_does_not_bypass_the_block_policy(redirect_direct_dials):
    # Fallback only rescues an upstream failure for an ALLOWED host; a blocked
    # host is still 403 and never reaches any origin, fallback or not.
    server = _start_proxy(_dead_upstream(fallback_direct=True))
    try:
        status, _ = _proxy_get(server.server_address[1], "http://private.example/")
    finally:
        server.shutdown()
    assert status == 403

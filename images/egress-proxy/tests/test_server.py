import http.client
import ipaddress
import socket
import threading
import time

import pytest
from proxy.policy import EgressPolicy
from proxy.server import ProxyServer


@pytest.fixture
def proxy():
    # Denylist a host so we can prove denylist enforcement without real DNS.
    policy = EgressPolicy(denylist=frozenset({"blocked.example"}))
    # Resolver that makes "private.example" look like an RFC1918 host and
    # "public.example" resolve to a loopback we can actually serve from a
    # local upstream; for the BLOCK paths we never connect, so the IP is fine.
    def resolver(host):
        return {
            "private.example": ["10.0.0.1"],
            "metadata.example": ["169.254.169.254"],
        }.get(host, ["93.184.216.34"])

    server = ProxyServer(("127.0.0.1", 0), policy, resolve=resolver)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield port
    server.shutdown()


def _proxy_get(proxy_port, url):
    conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=5)
    conn.request("GET", url)  # absolute-URI form => proxy request
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def test_http_request_to_rfc1918_is_blocked_403(proxy):
    status, body = _proxy_get(proxy, "http://private.example/")
    assert status == 403
    assert b"private_range" in body


def test_http_request_to_metadata_is_blocked_403(proxy):
    status, body = _proxy_get(proxy, "http://metadata.example/latest/meta-data/")
    assert status == 403
    assert b"link_local" in body


def test_http_request_to_denylisted_is_blocked_403(proxy):
    status, body = _proxy_get(proxy, "http://blocked.example/")
    assert status == 403
    assert b"denylisted" in body


def test_connect_to_rfc1918_is_refused(proxy):
    conn = http.client.HTTPConnection("127.0.0.1", proxy, timeout=5)
    conn.request("CONNECT", "private.example:443")
    resp = conn.getresponse()
    assert resp.status == 403
    conn.close()


def test_connect_splice_survives_client_half_close(monkeypatch):
    """Regression: a client that half-closes its send side (shutdown SHUT_WR)
    after sending its request — as Bun's fetch / many HTTP clients do — must
    still receive the FULL upstream response.

    The old splice did ``if not data: return`` on the first EOF from either
    socket, tearing down the whole tunnel (incl. the upstream) the moment the
    client half-closed — truncating the in-flight response (Bun surfaced this as
    'Cache input stream was empty', which broke the opencode driver).
    """
    # Local upstream: accept, read the request, wait, THEN send a known response
    # — i.e. respond only after the client has already half-closed.
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    upstream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    up_port = upstream.getsockname()[1]
    response = b"HELLO_FROM_UPSTREAM_" + b"y" * 2000

    def serve_upstream() -> None:
        try:
            conn, _ = upstream.accept()
        except OSError:
            return
        conn.recv(65536)        # the client's request bytes (sent before half-close)
        time.sleep(0.2)         # respond AFTER the client half-closes
        try:
            conn.sendall(response)
        except OSError:
            pass
        conn.close()

    threading.Thread(target=serve_upstream, daemon=True).start()

    # Resolve to a public IP (so the policy allows it), but redirect the proxy's
    # actual upstream connection to our loopback test server. Client→proxy
    # connections (loopback) pass through untouched.
    real_connect = socket.create_connection

    def fake_connect(addr, timeout=None, source_address=None):
        try:
            if ipaddress.ip_address(addr[0]).is_loopback:
                return real_connect(addr, timeout)
        except ValueError:
            pass
        return real_connect(("127.0.0.1", up_port), timeout)

    monkeypatch.setattr("socket.create_connection", fake_connect)

    server = ProxyServer(
        ("127.0.0.1", 0), EgressPolicy(denylist=frozenset()),
        resolve=lambda _h: ["93.184.216.34"],
    )
    pport = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    try:
        client = socket.create_connection(("127.0.0.1", pport), timeout=5)
        client.sendall(b"CONNECT up.example:443 HTTP/1.1\r\n\r\n")
        # Consume the proxy's CONNECT response (status line + headers).
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += client.recv(1024)
        # RFC 7231: a successful CONNECT is a bare '200 Connection Established'
        # with NO Content-Length / Connection headers (Bun mishandles the tunnel
        # otherwise — opencode's fetches failed with 'Unexpected server error').
        connect_head = buf.split(b"\r\n\r\n", 1)[0]
        assert connect_head == b"HTTP/1.1 200 Connection Established", connect_head
        # Send a request, then HALF-CLOSE the write side (the Bun behaviour).
        client.sendall(b"GET / HTTP/1.1\r\nHost: up.example\r\n\r\n")
        client.shutdown(socket.SHUT_WR)
        # Read the full response until EOF.
        got = buf.split(b"\r\n\r\n", 1)[1]
        client.settimeout(5)
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            got += chunk
        client.close()
        assert response in got, f"truncated after half-close: {got[:80]!r} (len {len(got)})"
    finally:
        server.shutdown()
        upstream.close()


def test_connect_uses_resolved_public_ip_not_hostname(monkeypatch):
    captured = []

    def resolver(host):
        return {"public.example": ["93.184.216.34"]}[host]

    _real_connect = socket.create_connection

    def fake_connect(addr, timeout=None, source_address=None):
        host_addr = addr[0]
        # Let the test client connect to the proxy server (loopback).
        # Intercept any non-loopback upstream connection (the one the proxy makes).
        try:
            if ipaddress.ip_address(host_addr).is_loopback:
                return _real_connect(addr, timeout, source_address)
        except ValueError:
            pass
        captured.append(addr)
        raise OSError("stop before tunnel splice")

    monkeypatch.setattr("socket.create_connection", fake_connect)
    server = ProxyServer(("127.0.0.1", 0), EgressPolicy(denylist=frozenset()), resolve=resolver)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("CONNECT", "public.example:443")
        resp = conn.getresponse()
        assert resp.status == 502
        conn.close()
    finally:
        server.shutdown()
    assert captured == [("93.184.216.34", 443)]


def _raw_send(proxy_port, raw: bytes) -> bytes:
    s = socket.create_connection(("127.0.0.1", proxy_port), timeout=5)
    s.sendall(raw)
    s.settimeout(5)
    buf = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except OSError:
        pass
    s.close()
    return buf


def test_malformed_request_line_returns_400(proxy):
    # A request line that does not split into method/target/version (line 40-41).
    resp = _raw_send(proxy, b"GET\r\n\r\n")
    assert resp.startswith(b"HTTP/1.1 400"), resp
    assert b"bad request line" in resp


def test_empty_request_line_closes_silently(proxy):
    # A blank first line → handler returns with no response (line 37).
    resp = _raw_send(proxy, b"\r\n")
    assert resp == b""


# ---------------------------------------------------------------------------
# Task 4: server resolve/decision branches
# ---------------------------------------------------------------------------

def _serve(policy, resolver):
    """Start a ProxyServer on an ephemeral port in a daemon thread.

    Returns (port, server) so the caller can shut it down after the test.
    """
    server = ProxyServer(("127.0.0.1", 0), policy, resolve=resolver)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    return port, server


def test_connect_to_allowed_ip_literal_then_502(monkeypatch):
    """IP-literal-allowed branch of _resolve_upstream_ip (server.py 82-83).

    When the CONNECT target is an allowed public IP literal (not a hostname)
    the server must skip DNS, classify the literal directly, and attempt to
    dial that exact IP.  We stop the dial (OSError → 502) to avoid real
    egress, then assert the captured dial target equals the literal sent by
    the client.
    """
    captured = []
    real_connect = socket.create_connection

    def fake_connect(addr, timeout=None, source_address=None):
        try:
            if ipaddress.ip_address(addr[0]).is_loopback:
                return real_connect(addr, timeout, source_address)
        except ValueError:
            pass
        captured.append(addr)
        raise OSError("stop before real egress")

    monkeypatch.setattr("socket.create_connection", fake_connect)
    # 8.8.8.8 is a real public IP; EgressPolicy(denylist=frozenset()) allows it.
    # 203.0.113.0/24 is the TEST-NET-3 documentation range, classified as private_range.
    port, server = _serve(EgressPolicy(denylist=frozenset()), lambda _h: ["8.8.8.8"])
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("CONNECT", "8.8.8.8:443")  # IP literal, allowed public address
        resp = conn.getresponse()
        assert resp.status == 502                # dial attempted, then failed
        conn.close()
    finally:
        server.shutdown()
    # The proxy must have tried to dial the literal IP, not any resolver result.
    assert captured == [("8.8.8.8", 443)]


def test_plain_get_dns_oserror_is_403_dns_failure():
    """OSError from the resolver (server.py 88-89) returns 403 dns_failure."""
    def resolver(_host):
        raise OSError("no DNS")

    port, server = _serve(EgressPolicy(denylist=frozenset()), resolver)
    try:
        status, body = _proxy_get(port, "http://broken.example/")
        assert status == 403
        assert b"dns_failure" in body
    finally:
        server.shutdown()


def test_plain_get_empty_resolution_is_403_dns_failure():
    """Empty address list from the resolver (server.py 91) returns 403 dns_failure."""
    port, server = _serve(EgressPolicy(denylist=frozenset()), lambda _h: [])
    try:
        status, body = _proxy_get(port, "http://ghost.example/")
        assert status == 403
        assert b"dns_failure" in body
    finally:
        server.shutdown()

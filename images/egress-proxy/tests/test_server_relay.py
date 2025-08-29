import http.client
import ipaddress
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from proxy.policy import EgressPolicy
from proxy.server import ProxyServer

UPSTREAM_BODY = b"UPSTREAM_OK_" + b"z" * 64


class _Upstream(BaseHTTPRequestHandler):
    captured_host = None

    def do_GET(self):
        _Upstream.captured_host = self.headers.get("Host")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("X-Upstream", "yes")
        self.end_headers()
        self.wfile.write(UPSTREAM_BODY)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def upstream():
    srv = HTTPServer(("127.0.0.1", 0), _Upstream)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()


@pytest.fixture
def relay_proxy(upstream, monkeypatch):
    """Proxy whose resolver returns a public IP (allowed) but whose upstream
    create_connection is redirected to the loopback upstream HTTP server."""
    real = socket.create_connection

    def fake(addr, timeout=None, source_address=None):
        try:
            if ipaddress.ip_address(addr[0]).is_loopback:
                return real(addr, timeout, source_address)
        except ValueError:
            pass
        return real(("127.0.0.1", upstream), timeout)

    monkeypatch.setattr("socket.create_connection", fake)
    server = ProxyServer(("127.0.0.1", 0), EgressPolicy(denylist=frozenset({"blocked.example"})),
                         resolve=lambda _h: ["93.184.216.34"])
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    yield port
    server.shutdown()


def _proxy_get(port, url):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", url)
    resp = conn.getresponse()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    body = resp.read()
    conn.close()
    return resp.status, headers, body


def test_plain_relay_allows_and_preserves_host(relay_proxy):
    status, headers, body = _proxy_get(relay_proxy, "http://allowed.example/path?q=1")
    assert status == 200
    assert body == UPSTREAM_BODY                     # full body relayed
    assert headers.get("x-upstream") == "yes"        # upstream header passed through
    assert _Upstream.captured_host == "allowed.example"   # Host preserved, not the IP


def test_plain_relay_strips_hop_by_hop_headers(relay_proxy):
    # transfer-encoding/connection must be re-synthesised, never echoed verbatim.
    status, headers, _ = _proxy_get(relay_proxy, "http://allowed.example/")
    assert status == 200
    assert headers.get("connection", "close").lower() == "close"
    assert "transfer-encoding" not in headers          # stripped; Content-Length set
    assert headers.get("content-length") == str(len(UPSTREAM_BODY))


def test_plain_relay_upstream_failure_is_502(monkeypatch):
    # Resolver allows, but the upstream dial fails → _handle_plain except → 502.
    real = socket.create_connection

    def fake(addr, timeout=None, source_address=None):
        try:
            if ipaddress.ip_address(addr[0]).is_loopback:
                return real(addr, timeout, source_address)
        except ValueError:
            pass
        raise OSError("upstream down")

    monkeypatch.setattr("socket.create_connection", fake)
    server = ProxyServer(("127.0.0.1", 0), EgressPolicy(denylist=frozenset()),
                         resolve=lambda _h: ["93.184.216.34"])
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    try:
        status, _, body = _proxy_get(port, "http://allowed.example/")
        assert status == 502 and b"upstream error" in body
    finally:
        server.shutdown()


def _read_audit_lines(capsys):
    out = capsys.readouterr().out
    return [json.loads(ln) for ln in out.splitlines() if ln.strip().startswith("{")]


def test_audit_line_for_allowed_request(relay_proxy, capsys):
    _proxy_get(relay_proxy, "http://allowed.example/")
    time.sleep(0.05)                                   # let the server thread flush
    recs = [r for r in _read_audit_lines(capsys) if r.get("msg") == "egress"]
    assert recs, "no egress audit line emitted"
    rec = recs[-1]
    assert rec["level"] == "info"
    assert rec["decision"] == "allow"
    assert rec["reason"] == "allowed"
    assert rec["method"] == "GET"
    assert rec["host"] == "allowed.example"
    assert rec["port"] == 80
    assert {"ts", "level", "msg"} <= rec.keys()


def test_audit_line_for_blocked_request(relay_proxy, capsys):
    _proxy_get(relay_proxy, "http://blocked.example/")   # denylisted
    time.sleep(0.05)
    recs = [r for r in _read_audit_lines(capsys) if r.get("msg") == "egress"]
    rec = recs[-1]
    assert rec["level"] == "warn"
    assert rec["decision"] == "block"
    assert rec["reason"] == "denylisted"
    assert rec["host"] == "blocked.example"

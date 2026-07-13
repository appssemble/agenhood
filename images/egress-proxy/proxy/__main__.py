"""Entrypoint: read config from env, start the forward proxy."""
from __future__ import annotations

import os
import sys

from proxy.logfmt import log_line
from proxy.policy import EgressPolicy, UpstreamPolicy
from proxy.server import ProxyServer


def main() -> None:
    host = os.environ.get("EGRESS_LISTEN_HOST", "0.0.0.0")
    port = int(os.environ.get("EGRESS_LISTEN_PORT", "8888"))
    policy = EgressPolicy.from_env(os.environ)
    try:
        upstream = UpstreamPolicy.from_env(os.environ)
    except ValueError as e:
        # Refuse to start on a contradictory routing config rather than guess.
        sys.stdout.write(log_line(level="error", msg="egress_proxy_config_error",
                                  error=str(e)) + "\n")
        sys.stdout.flush()
        raise SystemExit(2) from e

    sys.stdout.write(log_line(
        level="info", msg="egress_proxy_start",
        host=host, port=port, denylist_size=len(policy.denylist),
        # Credentials are never logged — only where traffic goes and how it is routed.
        upstream=f"{upstream.host}:{upstream.port}" if upstream else "",
        upstream_mode=upstream.mode if upstream else "off",
        upstream_hosts=len(upstream.hosts) if upstream else 0,
        upstream_fallback_direct=upstream.fallback_direct if upstream else False,
    ) + "\n")
    sys.stdout.flush()
    server = ProxyServer((host, port), policy, upstream=upstream)
    server.serve_forever()


if __name__ == "__main__":
    main()

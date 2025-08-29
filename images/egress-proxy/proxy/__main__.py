"""Entrypoint: read config from env, start the forward proxy."""
from __future__ import annotations

import os
import sys

from proxy.logfmt import log_line
from proxy.policy import EgressPolicy
from proxy.server import ProxyServer


def main() -> None:
    host = os.environ.get("EGRESS_LISTEN_HOST", "0.0.0.0")
    port = int(os.environ.get("EGRESS_LISTEN_PORT", "8888"))
    policy = EgressPolicy.from_env(os.environ)
    sys.stdout.write(log_line(
        level="info", msg="egress_proxy_start",
        host=host, port=port, denylist_size=len(policy.denylist),
    ) + "\n")
    sys.stdout.flush()
    server = ProxyServer((host, port), policy)
    server.serve_forever()


if __name__ == "__main__":
    main()

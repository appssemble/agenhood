"""Minimal stand-in for ``codex app-server`` used by the client tests."""

import json
import os
import sys


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        msg = json.loads(raw)
        if "id" not in msg:
            continue
        if "method" not in msg:
            send({"method": "test/reply", "params": msg})
            continue
        rid, method, params = msg["id"], msg["method"], msg.get("params") or {}
        if method == "initialize":
            if os.environ.get("STUB_FAIL_INIT"):
                send({"id": rid, "error": {"code": -32000, "message": "init refused"}})
            else:
                send({"id": rid, "result": {"userAgent": "stub"}})
        elif method == "test/emit":
            for note in params["messages"]:
                send(note)
            send({"id": rid, "result": {"emitted": len(params["messages"])}})
        elif method == "test/fail":
            send({"id": rid, "error": {"code": -32000, "message": params.get("message", "boom")}})
        elif method == "test/ask":
            send({"id": "srv-1", "method": "item/commandExecution/requestApproval", "params": {}})
            send({"id": rid, "result": {}})
        elif method == "test/stderr":
            sys.stderr.write(params["line"] + "\n")
            sys.stderr.flush()
            send({"id": rid, "result": {}})
        elif method == "test/exit":
            sys.exit(params.get("code", 3))
        elif method == "test/silent":
            pass
        else:
            send({"id": rid, "error": {"code": -32601, "message": f"unknown {method}"}})


main()

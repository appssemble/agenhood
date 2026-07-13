#!/usr/bin/env python3
"""Generate services/control_plane/control_plane/model_catalog.json.

Runs `opencode models` inside the agent image with placeholder API keys (to list
the full Anthropic + OpenAI + Zen catalogs), again with placeholder opencode
Zen/Go keys (to list the opencode-go plan models), and, if
MODELS_CATALOG_CODEX_AUTH is set to a path of a real ChatGPT oauth auth.json
(opencode format), again with that credential to list the OpenAI Codex
subscription models.

Codex-driver membership comes from Codex itself: if MODELS_CATALOG_CODEX_DEBUG_AUTH
points to a real ChatGPT auth.json (codex format — auth_mode/tokens), runs
`codex debug models` in the image to get the authoritative, per-account list of
models Codex can actually run (visibility == "list"). Without it, codex membership
falls back to the legacy `*codex*` substring heuristic (wrong in both directions —
see control_plane.model_catalog._codex_can_run).

Classifies via the shared control_plane.model_catalog.build_catalog_entries and
writes the artifact.

Run on agent-image / opencode / codex bumps:  make models-catalog
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "services" / "control_plane"))
from control_plane.model_catalog import build_catalog_entries  # noqa: E402

_IMAGE = os.environ.get("AGENT_IMAGE", "agent-runtime:v0.2.0")
_OUT = _REPO / "services/control_plane/control_plane/model_catalog.json"
_MODEL_LINE = re.compile(r"^[a-z0-9._-]+/[A-Za-z0-9._:-]+$")
_FALLBACK_CODEX = ["openai/gpt-5.4", "openai/gpt-5.3-codex-spark", "openai/gpt-5.5-pro"]

_PLACEHOLDER_AUTH = {
    "openai": {"type": "api", "key": "sk-placeholder-not-real"},
    "anthropic": {"type": "api", "key": "sk-ant-placeholder-not-real"},
}

# The base run must NOT configure opencode: free-vs-keyed Zen listings are only
# distinguishable by which run a model id appears in. The go run adds the
# opencode key placeholders so `opencode models` lists opencode-go/* and any
# key-gated Zen models (opencode lists a configured provider's models without
# calling the API).
_PLACEHOLDER_GO_AUTH = {
    **_PLACEHOLDER_AUTH,
    "opencode": {"type": "api", "key": "oc-placeholder-not-real"},
    "opencode-go": {"type": "api", "key": "oc-placeholder-not-real"},
}


def parse_model_ids(text: str) -> list[str]:
    """Extract `provider/model` ids from `opencode models` stdout."""
    return [ln.strip() for ln in text.splitlines() if _MODEL_LINE.match(ln.strip())]


def parse_codex_models(text: str) -> list[str]:
    """Authoritative Codex-runnable slugs from `codex debug models` JSON stdout.

    Keeps only models the picker should offer (visibility == "list"); drops
    internal/hidden entries such as ``codex-auto-review``.
    """
    data = json.loads(text)
    models = data if isinstance(data, list) else data.get("models", [])
    return [m["slug"] for m in models if m.get("visibility") == "list"]


def _run_opencode_models(auth: dict) -> list[str]:  # type: ignore[type-arg]
    with tempfile.TemporaryDirectory() as d:
        Path(d, "auth.json").write_text(json.dumps(auth))
        cmd = [
            "docker", "run", "--rm", "-v", f"{d}/auth.json:/seed/auth.json:ro",
            "--entrypoint", "sh", _IMAGE, "-c",
            "mkdir -p /home/agent/opencode && cp /seed/auth.json /home/agent/opencode/auth.json && "
            "HOME=/home/agent XDG_DATA_HOME=/home/agent XDG_CONFIG_HOME=/home/agent/.config "
            "XDG_CACHE_HOME=/home/agent/.cache opencode models",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=True)
    return parse_model_ids(res.stdout)


def _run_codex_debug_models(auth_path: str) -> list[str]:
    """Run `codex debug models` in the agent image with a codex-format auth.json.

    Returns the authoritative Codex-runnable slugs for that account. Codex fetches
    the set from its backend per-account, so the result reflects whatever ChatGPT
    plan ``auth_path`` holds (same build-time-snapshot caveat as the opencode runs).
    """
    auth = Path(auth_path).read_text()
    with tempfile.TemporaryDirectory() as d:
        Path(d, "auth.json").write_text(auth)
        cmd = [
            "docker", "run", "--rm", "-v", f"{d}/auth.json:/seed/auth.json:ro",
            "--entrypoint", "sh", _IMAGE, "-c",
            "mkdir -p /home/agent/.codex && cp /seed/auth.json /home/agent/.codex/auth.json && "
            "HOME=/home/agent CODEX_HOME=/home/agent/.codex codex debug models",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=True)
    return parse_codex_models(res.stdout)


def main() -> None:
    base = _run_opencode_models(_PLACEHOLDER_AUTH)
    go = _run_opencode_models(_PLACEHOLDER_GO_AUTH)
    go_only = [m for m in go if m not in base]
    print(f"opencode go run: {len(go_only)} additional model ids", file=sys.stderr)
    codex_auth_path = os.environ.get("MODELS_CATALOG_CODEX_AUTH")
    if codex_auth_path:
        sub = _run_opencode_models(json.loads(Path(codex_auth_path).read_text()))
    else:
        print("MODELS_CATALOG_CODEX_AUTH not set — using fallback Codex list", file=sys.stderr)
        sub = list(_FALLBACK_CODEX)

    codex_debug_auth = os.environ.get("MODELS_CATALOG_CODEX_DEBUG_AUTH")
    if codex_debug_auth:
        codex_ids = _run_codex_debug_models(codex_debug_auth)
        print(f"codex debug models: {len(codex_ids)} runnable slugs", file=sys.stderr)
    else:
        print(
            "MODELS_CATALOG_CODEX_DEBUG_AUTH not set — codex drivers via substring fallback",
            file=sys.stderr,
        )
        codex_ids = None
    entries = build_catalog_entries(base, sub, codex_ids=codex_ids, go_ids=go)
    entries.sort(key=lambda m: m["id"])
    _OUT.write_text(json.dumps({"models": entries}, indent=2) + "\n")
    print(f"wrote {_OUT} ({len(entries)} models)")


if __name__ == "__main__":
    main()

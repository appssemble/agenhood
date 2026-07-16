from __future__ import annotations

import argparse
import asyncio
import os

import uvicorn

import agentcore.tools  # noqa: F401 — side-effect: registers all built-in tools
from agentcore.drivers.base import Driver
from agentcore.drivers.claude_code import ClaudeCodeDriver
from agentcore.drivers.codex import CodexDriver
from agentcore.drivers.opencode import OpencodeDriver
from agentcore.drivers.vanilla import VanillaDriver
from agentcore.llm.anthropic import DEFAULT_BASE_URL, AnthropicClient
from agentcore.llm.openai_compat import DEFAULT_BASE_URL as OPENAI_DEFAULT_BASE_URL
from agentcore.llm.router import OPENCODE_GO_DEFAULT_BASE_URL, LLMRouter
from shim.app import create_app
from shim.git_ops import GitOps


def build_drivers() -> dict[str, Driver]:
    base_url = os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL)
    router = LLMRouter(
        anthropic_base_url=base_url,
        openai_base_url=os.environ.get("OPENAI_BASE_URL", OPENAI_DEFAULT_BASE_URL),
        opencode_go_base_url=os.environ.get(
            "OPENCODE_GO_BASE_URL", OPENCODE_GO_DEFAULT_BASE_URL
        ),
    )
    return {
        "vanilla": VanillaDriver(llm=AnthropicClient(base_url=base_url), router=router),
        # opencode + codex + claude-code shell out to their CLI binaries
        # (no LLM client needed).
        "opencode": OpencodeDriver(),
        "codex": CodexDriver(),
        "claude-code": ClaudeCodeDriver(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="agent-runtime shim")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--workspace", default="/workspace")
    args = parser.parse_args()

    token = os.environ.get("SHIM_TOKEN", "")

    os.makedirs(os.path.join(args.workspace, ".agent-runtime"), exist_ok=True)

    # Workspace repo init is best-effort at boot; every git op also lazily
    # ensures the repo, so a failure here only delays initialization.
    try:
        asyncio.run(GitOps(args.workspace).ensure_repo())
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: workspace git init failed: {exc}")

    max_workers = int(os.environ.get("SHIM_MAX_WORKERS", "4"))
    app = create_app(
        workspace=args.workspace, token=token, drivers=build_drivers(),
        max_workers=max_workers,
    )
    # Pin the stdlib asyncio loop. uvicorn[standard] installs uvloop and would
    # otherwise select it, but uvloop's subprocess does not accept the
    # privilege-drop kwargs (user/group/extra_groups) that sandbox.drop_kwargs
    # passes to asyncio.create_subprocess_exec — every untrusted task spawn would
    # die with "unexpected kwargs". Privsep correctness outweighs uvloop's speed
    # for the shim's lightweight control surface.
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info", loop="asyncio")


if __name__ == "__main__":
    main()

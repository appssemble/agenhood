"""Driver interfaces and registry."""

from agentcore.drivers import (
    api as _api,  # noqa: F401  (self-registration)
    claude_code,  # noqa: F401  (claude-code CLI)
    codex,  # noqa: F401  (Unit 3 — codex CLI)
    opencode,  # noqa: F401  (Unit 3)
    vanilla,  # noqa: F401  (Unit 1)
)

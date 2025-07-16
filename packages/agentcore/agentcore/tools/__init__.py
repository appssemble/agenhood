"""Tool interfaces and registry.

Importing this package side-effects: all built-in tool modules are imported
so their module-level ``register()`` calls execute and populate ``TOOLS``.
"""

# These imports are required — each module calls register() at module level.
import agentcore.tools.files  # noqa: F401
import agentcore.tools.shell  # noqa: F401
import agentcore.tools.web  # noqa: F401

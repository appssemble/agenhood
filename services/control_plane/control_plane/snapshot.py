from __future__ import annotations

from typing import Any

from agentcore.models import AgentConfig, ResolvedLimits, ShimTaskRequest, TaskBody


def snapshot_config(config: AgentConfig) -> dict[str, Any]:
    """Return a verbatim, JSON-serializable copy of the config for tasks.config_snapshot."""
    return config.model_dump()


def build_shim_request(
    *,
    task_id: str,
    body: TaskBody,
    config: AgentConfig,
    limits: ResolvedLimits,
    credential: str,
) -> ShimTaskRequest:
    return ShimTaskRequest(
        task_id=task_id,
        task=body,
        config=config,
        limits=limits,
        llm_credential=credential,
    )

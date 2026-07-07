from __future__ import annotations

from ulid import ULID


def _ulid_lower() -> str:
    # ULID is Crockford base32 (uppercase). Lowercase for DNS-safe docker names.
    return str(ULID()).lower()


def new_container_id() -> str:
    return "con_" + _ulid_lower()


def new_task_id() -> str:
    return "tsk_" + _ulid_lower()


def new_template_id() -> str:
    return "tpl_" + _ulid_lower()


def new_skill_id() -> str:
    return "skl_" + _ulid_lower()


def new_deploy_key_id() -> str:
    return "dk_" + _ulid_lower()


def new_mcp_id() -> str:
    return "mcp_" + _ulid_lower()


def new_prompt_id() -> str:
    return "prm_" + _ulid_lower()


def new_scheduled_task_id() -> str:
    return "sch_" + _ulid_lower()


def new_workflow_id() -> str:
    return "wf_" + _ulid_lower()


def new_workflow_run_id() -> str:
    return "wfr_" + _ulid_lower()


def docker_name_for(container_id: str) -> str:
    # Strip the con_ prefix; the remainder is already lowercase + DNS-safe.
    suffix = container_id[len("con_"):]
    return f"agent-c-{suffix}"


def volume_name_for(container_id: str) -> str:
    return f"agent-vol-{container_id}"

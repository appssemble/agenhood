import re

import pytest

from control_plane.ids import docker_name_for, new_container_id, new_task_id, new_template_id

pytestmark = pytest.mark.unit


def test_ids_have_expected_prefixes():
    assert new_container_id().startswith("con_")
    assert new_task_id().startswith("tsk_")
    assert new_template_id().startswith("tpl_")


def test_ids_are_unique():
    assert new_container_id() != new_container_id()


def test_docker_name_strips_prefix_and_is_dns_safe():
    cid = new_container_id()
    name = docker_name_for(cid)
    assert name == "agent-c-" + cid[len("con_"):]
    # DNS-safe: lowercase alnum + hyphen only
    assert re.fullmatch(r"agent-c-[0-9a-z]+", name)

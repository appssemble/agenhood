import pytest
from control_plane.ids import new_workflow_id, new_workflow_run_id

pytestmark = pytest.mark.unit


def test_workflow_ids_have_prefixes_and_are_unique():
    wid = new_workflow_id()
    rid = new_workflow_run_id()
    assert wid.startswith("wf_") and wid == wid.lower()
    assert rid.startswith("wfr_") and rid == rid.lower()
    assert new_workflow_id() != wid
    assert new_workflow_run_id() != rid

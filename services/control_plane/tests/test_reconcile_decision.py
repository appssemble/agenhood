import pytest

from control_plane.docker_ctl import DockerStateInfo  # adjust to probed path
from control_plane.reconciler import ReconcileAction, reconcile_decision

pytestmark = pytest.mark.unit


def ds(present, status=None, exit_code=0, oom=False, readyz=None):
    info = DockerStateInfo(present=present, status=status, exit_code=exit_code, oom_killed=oom)
    return info, readyz


def test_running_up_ready_adopt():
    info, readyz = ds(True, "running", readyz=True)
    a = reconcile_decision("running", info, readyz_ok=True, volume_exists=True)
    assert a == ReconcileAction.ADOPT_RUNNING


def test_running_up_unready_recover():
    info, _ = ds(True, "running")
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RECOVER


def test_running_exited_clean_with_volume_to_paused():
    info, _ = ds(True, "exited", exit_code=0, oom=False)
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.SET_PAUSED


def test_running_exited_nonzero_recovers():
    info, _ = ds(True, "exited", exit_code=137, oom=False)
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RECOVER


def test_running_oomkilled_recovers():
    info, _ = ds(True, "exited", exit_code=137, oom=True)
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RECOVER


def test_running_missing_with_volume_recovers():
    info, _ = ds(False)
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RECOVER


def test_running_missing_no_volume_errors():
    info, _ = ds(False)
    a = reconcile_decision("running", info, readyz_ok=False, volume_exists=False)
    assert a == ReconcileAction.SET_ERROR


def test_paused_exited_noop():
    info, _ = ds(True, "exited")
    a = reconcile_decision("paused", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.NOOP


def test_paused_up_ready_adopts_running():
    info, _ = ds(True, "running")
    a = reconcile_decision("paused", info, readyz_ok=True, volume_exists=True)
    assert a == ReconcileAction.ADOPT_RUNNING


def test_paused_up_not_ready_stops_to_match_db():
    info, _ = ds(True, "running")
    a = reconcile_decision("paused", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.STOP_TO_PAUSED


def test_provisioning_up_ready_finishes_running():
    info, _ = ds(True, "running")
    a = reconcile_decision("provisioning", info, readyz_ok=True, volume_exists=True)
    assert a == ReconcileAction.FINISH_TO_RUNNING


def test_provisioning_up_not_ready_errors():
    info, _ = ds(True, "running")
    a = reconcile_decision("provisioning", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.DESTROY_PARTIAL_TO_ERROR


def test_provisioning_missing_errors():
    info, _ = ds(False)
    a = reconcile_decision("provisioning", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.DESTROY_PARTIAL_TO_ERROR


def test_resuming_up_ready_finishes_running():
    info, _ = ds(True, "running")
    a = reconcile_decision("resuming", info, readyz_ok=True, volume_exists=True)
    assert a == ReconcileAction.FINISH_TO_RUNNING


def test_resuming_exited_back_to_paused():
    info, _ = ds(True, "exited")
    a = reconcile_decision("resuming", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.SET_PAUSED


def test_pausing_exited_finishes_paused():
    info, _ = ds(True, "exited")
    a = reconcile_decision("pausing", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.FINISH_TO_PAUSED


def test_pausing_up_reissue_stop():
    info, _ = ds(True, "running")
    a = reconcile_decision("pausing", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.STOP_TO_PAUSED


def test_archiving_present_finishes_archived():
    info, _ = ds(True, "exited")
    a = reconcile_decision("archiving", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RM_TO_ARCHIVED


def test_archiving_missing_finishes_archived():
    info, _ = ds(False)
    a = reconcile_decision("archiving", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.SET_ARCHIVED


def test_archived_missing_noop():
    info, _ = ds(False)
    a = reconcile_decision("archived", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.NOOP


def test_archived_present_removes_stale_stays_archived():
    info, _ = ds(True, "exited")
    a = reconcile_decision("archived", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.RM_STALE_STAY_ARCHIVED


def test_recovering_any_reenters_recovery():
    for info, _ in (ds(True, "running"), ds(True, "exited"), ds(False)):
        a = reconcile_decision("recovering", info, readyz_ok=False, volume_exists=True)
        assert a == ReconcileAction.RECOVER


def test_destroying_present_finishes_destroy():
    info, _ = ds(True, "exited")
    a = reconcile_decision("destroying", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.FINISH_DESTROY


def test_error_any_left_alone():
    for info, _ in (ds(True, "running"), ds(False)):
        a = reconcile_decision("error", info, readyz_ok=False, volume_exists=True)
        assert a == ReconcileAction.NOOP


def test_deleting_finishes_delete():
    info, _ = ds(True, "exited")
    a = reconcile_decision("deleting", info, readyz_ok=False, volume_exists=True)
    assert a == ReconcileAction.FINISH_DELETE


def test_deleting_finishes_delete_when_container_gone():
    info, _ = ds(False)
    a = reconcile_decision("deleting", info, readyz_ok=False, volume_exists=False)
    assert a == ReconcileAction.FINISH_DELETE

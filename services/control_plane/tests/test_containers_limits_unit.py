"""Task 14: Unit tests for the max_containers create cap helper."""
import pytest

from control_plane.routers.containers import MaxContainersReached, assert_under_container_cap


def test_under_cap_ok():
    assert_under_container_cap(current_count=5, max_containers=2000)  # no raise


def test_at_cap_rejected():
    with pytest.raises(MaxContainersReached):
        assert_under_container_cap(current_count=2000, max_containers=2000)


def test_over_cap_rejected():
    with pytest.raises(MaxContainersReached):
        assert_under_container_cap(current_count=2001, max_containers=2000)

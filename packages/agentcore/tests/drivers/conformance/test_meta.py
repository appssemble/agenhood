# packages/agentcore/tests/drivers/conformance/test_meta.py
import pytest

from agentcore.drivers.base import DRIVERS
from tests.drivers.conformance.matrix import ALL_DRIVERS

pytestmark = pytest.mark.unit

_EXPECTED_NAMES = {"vanilla", "opencode", "codex", "claude-code"}


def test_every_registered_driver_is_in_the_matrix():
    matrix_names = {e.name for e in ALL_DRIVERS}
    assert set(DRIVERS.keys()) == matrix_names


def test_matrix_contains_expected_drivers():
    """Fallback for shim.main (not importable from agentcore venv).

    Asserts the hard-coded expected driver set instead of comparing against
    build_drivers() — equivalence is already covered by
    services/shim/tests/test_main_drivers.py.
    """
    matrix_names = {e.name for e in ALL_DRIVERS}
    assert matrix_names == _EXPECTED_NAMES

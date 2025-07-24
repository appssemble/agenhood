# packages/agentcore/tests/drivers/conformance/test_conformance.py
import json

import pytest

from tests.drivers.conformance import invariants as inv
from tests.drivers.conformance import matrix as M
from tests.drivers.conformance.golden_helper import golden
from tests.drivers.conformance.matrix import ALL_DRIVERS, SCENARIOS, applies

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("entry", ALL_DRIVERS, ids=lambda e: e.name)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_driver_conformance(scenario, entry):
    if not applies(scenario, entry):
        pytest.skip(f"{scenario.id} n/a for {entry.name}")
    scenario.run(entry)


# ---------------------------------------------------------------------------
# Event-stream golden conformance
# ---------------------------------------------------------------------------

EVENT_CASES = ["success", "error", "multi_step", "cancel", "timeout", "missing_binary"]


@pytest.mark.parametrize("entry", ALL_DRIVERS, ids=lambda e: e.name)
@pytest.mark.parametrize("case", EVENT_CASES)
def test_event_stream_conformance(case, entry, monkeypatch):
    events, ws = M._events_for(entry, case, monkeypatch)
    inv.assert_no_secret_leak(json.dumps(M.to_jsonable_events(events)))
    inv.assert_single_terminal_status(events)
    golden(f"{entry.name}/events_{case}", events, subs=M.SUBS(ws))

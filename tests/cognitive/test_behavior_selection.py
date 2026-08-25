"""COG-EVAL-1: Behavior selection benchmark (incl. preference promotion)."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.BEHAVIOR_SELECTION)


@pytest.mark.cognitive
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_behavior_selection(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

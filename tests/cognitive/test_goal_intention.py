"""COG-EVAL-1: Goal/intention lifecycle benchmark."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.GOAL_INTENTION)


@pytest.mark.cognitive
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_goal_intention(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

"""COG-EVAL-1: Learning safety / convergence benchmark."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.LEARNING)


@pytest.mark.cognitive
@pytest.mark.learning
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_learning(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

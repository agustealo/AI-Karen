"""COG-EVAL-1: Salience semantics benchmark."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.SALIENCE)


@pytest.mark.cognitive
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_salience(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

"""COG-EVAL-1: Meta-cognition benchmark."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.META_COGNITION)


@pytest.mark.cognitive
@pytest.mark.meta
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_meta_cognition(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

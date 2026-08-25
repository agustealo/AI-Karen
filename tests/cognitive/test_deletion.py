"""COG-EVAL-1: Deletion / retention benchmark."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.DELETION)


@pytest.mark.cognitive
@pytest.mark.deletion
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_deletion(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

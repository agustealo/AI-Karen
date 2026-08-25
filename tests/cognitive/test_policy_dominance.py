"""COG-EVAL-1: Policy dominance benchmark (tenant/user constraints)."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.scenario_runner import check, scenarios_for

CASES = scenarios_for(ScenarioKind.POLICY_DOMINANCE)


@pytest.mark.cognitive
@pytest.mark.policy
@pytest.mark.parametrize("scenario", CASES, ids=[s.scenario_id for s in CASES])
def test_policy_dominance(scenario):
    failures = check(scenario)
    assert not failures, " | ".join(failures)

"""Executable closure gates for COG-CONVERGE-1.

These tests turn the declarative COG-EVAL-1 scenarios into CI-enforced proof.
They deliberately exercise the real cognitive modules through scenario_runner;
there are no provider calls, mocks, or relaxed expectations here.
"""

from __future__ import annotations

import pytest

from benchmarks.cognitive.contracts import CognitiveResult, ExpectedSpec, Scenario, ScenarioKind
from benchmarks.cognitive.scenario_runner import load_scenarios, run_scenario


SCENARIOS = load_scenarios()
POLICY_SCENARIOS = [scenario for scenario in SCENARIOS if scenario.kind is ScenarioKind.POLICY_DOMINANCE]


def _assert_expected(scenario: Scenario, result: CognitiveResult) -> None:
    expected: ExpectedSpec = scenario.expected

    assert result.scenario_id == scenario.scenario_id
    assert result.kind is scenario.kind

    if expected.result:
        assert result.verdict == expected.result, (
            f"{scenario.scenario_id}: expected verdict {expected.result!r}, "
            f"got {result.verdict!r}"
        )

    assert expected.confidence_min <= result.confidence <= expected.confidence_max, (
        f"{scenario.scenario_id}: confidence {result.confidence} outside "
        f"[{expected.confidence_min}, {expected.confidence_max}]"
    )

    for field_name in (
        "active",
        "retained",
        "tenant_scoped",
        "policy_violation",
        "promoted_to_trusted",
    ):
        expected_value = getattr(expected, field_name)
        if expected_value is not None:
            assert getattr(result, field_name) is expected_value, (
                f"{scenario.scenario_id}: expected {field_name}={expected_value!r}, "
                f"got {getattr(result, field_name)!r}"
            )

    expected_present = set(expected.appears_in or [])
    missing = expected_present.difference(result.appears_in)
    assert not missing, f"{scenario.scenario_id}: expected references missing from result: {sorted(missing)}"

    forbidden = set(expected.not_appears_in or [])
    leaked = forbidden.intersection(result.appears_in)
    assert not leaked, f"{scenario.scenario_id}: forbidden references appeared in result: {sorted(leaked)}"

    assert not result.defects, (
        f"{scenario.scenario_id}: benchmark exposed defects: "
        f"{[defect.to_dict() for defect in result.defects]}"
    )


def test_cognitive_benchmark_has_scenarios() -> None:
    assert SCENARIOS, "COG-EVAL-1 fixture discovery returned no scenarios"
    assert {scenario.kind for scenario in SCENARIOS} == set(ScenarioKind), (
        "cognitive benchmark must retain coverage for every canonical ScenarioKind"
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_cognitive_benchmark_scenario_contract(scenario: Scenario) -> None:
    _assert_expected(scenario, run_scenario(scenario))


def test_policy_dominance_has_scenario() -> None:
    assert POLICY_SCENARIOS, "policy-dominance fixture coverage is required"


@pytest.mark.parametrize("scenario", POLICY_SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_policy_dominance_overrides_cognitive_act_signal(scenario: Scenario) -> None:
    result = run_scenario(scenario)
    _assert_expected(scenario, result)

    assert scenario.expected.result == "POLICY_WINS", (
        f"{scenario.scenario_id}: policy fixture must explicitly require POLICY_WINS"
    )
    assert scenario.expected.policy_violation is True, (
        f"{scenario.scenario_id}: policy fixture must explicitly require a blocked policy outcome"
    )
    assert result.verdict == "POLICY_WINS"
    assert result.policy_violation is True

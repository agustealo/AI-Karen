"""KCOG-00A2: no manufactured causal inference without identification."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.reasoning.causal import (
    CausalIdentificationError,
    CausalReasoningEngine,
    CognitiveCausalReasoner,
)


def _correlated_observations() -> list[dict[str, object]]:
    return [
        {"treatment": i % 2, "outcome": (i % 2) * 100 + i}
        for i in range(20)
    ]


def test_unadjusted_treatment_control_difference_is_not_causal_effect() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations(_correlated_observations())

    with pytest.raises(CausalIdentificationError, match="causal_effect_unidentifiable"):
        engine.estimate_causal_effect("treatment", "outcome")

    # Pretending to supply adjustment variables does not supply identification.
    with pytest.raises(CausalIdentificationError, match="causal_effect_unidentifiable"):
        engine.estimate_causal_effect("treatment", "outcome", {"confounder"})


def test_missing_groups_do_not_become_zero_causal_effect() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations([{"treatment": 1, "outcome": 20}])

    with pytest.raises(CausalIdentificationError):
        engine.estimate_causal_effect("treatment", "outcome")


def test_intervention_does_not_predict_descendants_or_record_a_fake_action() -> None:
    engine = CausalReasoningEngine()
    engine.causal_graph.add_edge("x", "y", 0.8, 0.9, evidence=["source"])
    with pytest.raises(CausalIdentificationError, match="intervention_effect_unidentifiable"):
        engine.do_intervention("x", 1)

    assert engine.interventions == []
    assert engine.causal_graph.edges[("x", "y")].confidence == 0.9


def test_counterfactual_does_not_assign_fifty_percent_probability() -> None:
    engine = CausalReasoningEngine()
    with pytest.raises(CausalIdentificationError, match="counterfactual_unidentifiable"):
        engine.generate_counterfactual("change x", [("x", 1)])

    assert engine.interventions == []


def test_causal_explanation_does_not_invent_actual_or_necessary_causes() -> None:
    engine = CausalReasoningEngine()
    engine.causal_graph.add_edge("a", "b", 0.8, 0.9, evidence=["source"])
    with pytest.raises(CausalIdentificationError, match="causal_explanation_unidentifiable"):
        engine.explain_outcome("b", 1, {"a": 1})


def test_responsibility_without_identification_is_not_zero() -> None:
    engine = CausalReasoningEngine()
    with pytest.raises(CausalIdentificationError, match="causal_responsibility_unidentifiable"):
        engine.assess_responsibility("outcome", ["agent"], {})


def test_cognitive_causal_wrapper_propagates_identification_abstention() -> None:
    reasoner = CognitiveCausalReasoner()
    with pytest.raises(CausalIdentificationError):
        reasoner.explain_outcome("outcome", 1, {"cause": 1})

    with pytest.raises(CausalIdentificationError):
        reasoner.compare_counterfactuals({"x": 0}, [("x", 1)])

    with pytest.raises(CausalIdentificationError):
        reasoner.compare_counterfactuals({"x": 0}, [])


def test_compatible_observation_recording_survives_safety_guard() -> None:
    engine = CausalReasoningEngine()
    evidence = _correlated_observations()
    engine.learn_from_observations(evidence)

    assert engine.observations == evidence
    assert engine.causal_graph.edges == {}

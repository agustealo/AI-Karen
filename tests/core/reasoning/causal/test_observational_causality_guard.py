"""KCOG-00A: observational associations cannot promote unverified causes."""

from __future__ import annotations

from ai_karen_engine.core.reasoning.causal.engine import CausalReasoningEngine


def test_perfect_correlation_cannot_create_causes() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations(
        [{"a": i, "b": i * 10} for i in range(1, 21)]
    )

    assert len(engine.observations) == 20
    assert engine.causal_graph.edges == {}
    assert engine.causal_graph.nodes == set()


def test_temporal_precedence_is_not_causal_identification() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations(
        [
            {"a": i, "b": i * 3, "a_time": i, "b_time": i + 1}
            for i in range(1, 21)
        ]
    )

    # Time-order evidence can inform hypotheses but cannot verify causes.
    assert engine.causal_graph.edges == {}


def test_missing_time_does_not_assume_direction() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations(
        [{"x": i, "y": i * 2} for i in range(1, 21)]
    )

    assert engine._determine_direction("x", "y") is False


def test_observations_do_not_overwrite_explicit_graph_edges() -> None:
    engine = CausalReasoningEngine()
    engine.causal_graph.add_edge(
        cause="approved_cause",
        effect="approved_effect",
        strength=0.8,
        confidence=0.9,
        mechanism="externally_verified",
        evidence=["approved-source-id"],
    )
    before = dict(engine.causal_graph.edges)

    engine.learn_from_observations(
        [{"x": i, "y": 5 * i} for i in range(1, 21)]
    )

    assert engine.causal_graph.edges == before
    assert set(engine.causal_graph.edges) == {
        ("approved_cause", "approved_effect")
    }


def test_small_observational_sample_remains_noncausal() -> None:
    engine = CausalReasoningEngine()
    engine.learn_from_observations([{"x": 2, "y": 10}])

    assert len(engine.observations) == 1
    assert engine.causal_graph.edges == {}

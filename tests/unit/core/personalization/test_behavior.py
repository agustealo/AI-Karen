"""Unit tests for user behavior aggregation."""

from __future__ import annotations

from datetime import datetime

from ai_karen_engine.core.personalization.behavior.aggregator import BehaviorAggregator
from ai_karen_engine.core.personalization.behavior.contracts import BehaviorObservation


def _observation(observation_id: str) -> BehaviorObservation:
    return BehaviorObservation(
        observation_id=observation_id,
        pattern_id="",
        user_id="u1",
        tenant_id="t1",
        context_signature="domain=architecture",
        action="accept_suggestion",
        outcome="accepted",
        observed_at=datetime.utcnow(),
        metadata={"confidence": 0.8},
    )


def test_observation_becomes_user_behavior_candidate() -> None:
    candidate = BehaviorAggregator().observe(_observation("obs-1"))

    assert candidate.pattern_type == "accept_suggestion"
    assert candidate.context_signature == "domain=architecture"
    assert candidate.observation == "accepted"
    assert candidate.confidence == 0.8


def test_repeated_observations_can_be_promoted_without_hidden_store() -> None:
    aggregator = BehaviorAggregator()
    candidates = [
        aggregator.observe(_observation("obs-1")),
        aggregator.observe(_observation("obs-2")),
    ]

    patterns = aggregator.promote_candidates(candidates)

    assert len(patterns) == 1
    assert patterns[0].observation_count == 2
    assert patterns[0].recurrence == "repeated"


__all__ = ["test_observation_becomes_user_behavior_candidate"]

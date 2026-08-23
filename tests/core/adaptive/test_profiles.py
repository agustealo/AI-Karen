"""Tests for adaptive profiles."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.adaptive.learning.aggregates import EvidenceAggregator
from ai_karen_engine.core.adaptive.profiles.agent import AgentProfileStore
from ai_karen_engine.core.adaptive.profiles.capability import CapabilityProfileStore


@pytest.fixture
def aggregator():
    return EvidenceAggregator()


def test_capability_profile_store(aggregator):
    store = CapabilityProfileStore(aggregator=aggregator)
    from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
    obs = ActionOutcomeObservation(
        observation_id="obs1",
        source_outcome_id="out1",
        action_type="use_tool",
        target_id="github",
        execution_status="success",
        latency_ms=100.0,
    )
    aggregator.add_observation(obs)
    profile = store.get("github")
    assert profile.sample_count == 1
    assert profile.success_rate > 0.0


def test_agent_profile_store(aggregator):
    store = AgentProfileStore(aggregator=aggregator)
    from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
    obs = ActionOutcomeObservation(
        observation_id="obs1",
        source_outcome_id="out1",
        action_type="use_multi_agent",
        target_id="team_alpha",
        execution_status="success",
        latency_ms=200.0,
    )
    aggregator.add_observation(obs)
    profile = store.get("team_alpha")
    assert profile.sample_count == 1
    assert profile.success_rate > 0.0


def test_capability_profile_as_dict(aggregator):
    store = CapabilityProfileStore(aggregator=aggregator)
    result = store.as_dict("nonexistent")
    assert result["capability_id"] == "nonexistent"
    assert result["sample_count"] == 0

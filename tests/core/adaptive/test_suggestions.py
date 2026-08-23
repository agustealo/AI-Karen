"""Tests for adaptive suggestions."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.contracts import (
    BehaviorPatternSummary,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.suggestions.contracts import SuggestionCandidate
from ai_karen_engine.core.adaptive.suggestions.dedupe import SuggestionDedupeStore
from ai_karen_engine.core.adaptive.suggestions.engine import SuggestionEngine
from ai_karen_engine.core.adaptive.suggestions.policy import SuggestionPolicy


class MockTaskSignature:
    def __init__(self):
        pass


def test_suggestion_dedupe():
    store = SuggestionDedupeStore()
    candidate = SuggestionCandidate(
        suggestion_id="s1",
        suggestion_type="workflow_automation",
        subject="Save workflow",
        dedupe_key="workflow_automation",
    )
    assert not store.is_duplicate(candidate, cooldown_seconds=3600)
    store.record(candidate)
    assert store.is_duplicate(candidate, cooldown_seconds=3600)


def test_suggestion_policy_threshold():
    policy = SuggestionPolicy(threshold=0.7)
    candidate = SuggestionCandidate(
        suggestion_id="s1",
        suggestion_type="tip",
        subject="Tip",
        utility=0.5,
        interruption_cost=0.1,
        dedupe_key="tip",
    )
    assert not policy.should_surface(candidate)


def test_suggestion_policy_interruption():
    policy = SuggestionPolicy()
    candidate = SuggestionCandidate(
        suggestion_id="s1",
        suggestion_type="tip",
        subject="Tip",
        utility=0.9,
        interruption_cost=0.9,
        dedupe_key="tip",
    )
    assert not policy.should_surface(candidate)


def test_suggestion_engine_generate():
    engine = SuggestionEngine()
    task = MockTaskSignature()
    user = UserStateSnapshot(user_id="u1")
    behavior = BehaviorPatternSummary(user_id="u1", workflow_usage_rate=0.5)
    capabilities = SystemCapabilitySnapshot(memory_available=True, available_agents=["a1", "a2"])

    suggestions = engine.generate(task, user, behavior, capabilities)
    assert isinstance(suggestions, list)


def test_suggestion_feedback_dismissal():
    engine = SuggestionEngine()
    candidate = SuggestionCandidate(
        suggestion_id="s1",
        suggestion_type="workflow_automation",
        subject="Save workflow",
        dedupe_key="workflow_automation",
    )
    engine.record_feedback(candidate, "dismissed")
    assert engine._policy._dedupe_store.dismissal_count("workflow_automation") == 1

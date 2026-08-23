"""Tests for adaptive contracts."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    AdaptiveRecommendation,
    AdaptiveRecommendationSet,
    BehaviorPatternSummary,
    ResolvedPreferences,
    ScoreComponents,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)


def test_user_state_snapshot_defaults():
    snapshot = UserStateSnapshot(user_id="u1")
    assert snapshot.user_id == "u1"
    assert snapshot.tenant_id == "default"
    assert snapshot.locality_preference == "any"


def test_resolved_preferences_defaults():
    prefs = ResolvedPreferences()
    assert prefs.model_locality == "any"
    assert prefs.prefers_local is False


def test_score_components_utility():
    components = ScoreComponents(
        task_fit=0.8,
        user_preference_fit=0.7,
        historical_success=0.9,
        latency_penalty=-0.1,
        risk_penalty=-0.2,
        cost_penalty=-0.05,
        interruption_penalty=-0.05,
        confidence=0.8,
    )
    utility = components.utility
    assert 0.0 <= utility <= 1.0


def test_adaptive_recommendation_set_top():
    rec1 = AdaptiveRecommendation(
        recommendation_id="r1",
        action_type=AdaptiveActionType.RESPOND_DIRECTLY,
        utility_score=0.9,
    )
    rec2 = AdaptiveRecommendation(
        recommendation_id="r2",
        action_type=AdaptiveActionType.USE_TOOL,
        utility_score=0.7,
    )
    rec_set = AdaptiveRecommendationSet(
        request_id="req1",
        correlation_id="corr1",
        recommendations=[rec1, rec2],
    )
    assert rec_set.top_recommendation is rec1


def test_adaptive_action_catalog():
    from ai_karen_engine.core.adaptive.candidates.catalog import AdaptiveActionCatalog
    assert AdaptiveActionCatalog.is_valid_action("respond_directly")
    assert not AdaptiveActionCatalog.is_valid_action("use_vllm")
    assert AdaptiveActionCatalog.is_provider_specific("use_vllm")
    assert not AdaptiveActionCatalog.is_provider_specific("use_tool")


def test_system_capability_snapshot():
    snapshot = SystemCapabilitySnapshot(
        available_tools=["github", "filesystem"],
        local_only_mode=True,
    )
    assert "github" in snapshot.available_tools
    assert snapshot.local_only_mode is True


def test_behavior_pattern_summary():
    pattern = BehaviorPatternSummary(user_id="u1", total_interactions=10)
    assert pattern.total_interactions == 10
    assert pattern.clarification_rate == 0.0

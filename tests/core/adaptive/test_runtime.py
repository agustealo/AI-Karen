"""Tests for adaptive runtime."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    AdaptiveRecommendationSet,
    BehaviorPatternSummary,
    HistoricalEvidence,
    ResolvedPreferences,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.runtime import AdaptiveRuntime


class MockTaskSignature:
    def __init__(self, complexity="simple", ambiguity="clear", risk="low", tool_requirements=None):
        self.complexity = complexity
        self.ambiguity = ambiguity
        self.risk = risk
        self.tool_requirements = tool_requirements or []


@pytest.fixture
def runtime():
    return AdaptiveRuntime()


@pytest.mark.asyncio
async def test_adaptive_runtime_recommend(runtime):
    task = MockTaskSignature(complexity="simple", ambiguity="clear", risk="low")
    user = UserStateSnapshot(user_id="u1", tenant_id="t1")
    prefs = ResolvedPreferences()
    behavior = BehaviorPatternSummary(user_id="u1", tenant_id="t1")
    capabilities = SystemCapabilitySnapshot(
        available_tools=["github"],
        available_agents=["analyst"],
        available_workflows=["w1"],
    )
    evidence = HistoricalEvidence()

    recs = await runtime.recommend(
        task_signature=task,
        user_state=user,
        resolved_preferences=prefs,
        behavior_patterns=behavior,
        system_capabilities=capabilities,
        historical_evidence=evidence,
    )
    assert isinstance(recs, AdaptiveRecommendationSet)
    assert len(recs.recommendations) > 0
    assert recs.top_recommendation is not None


@pytest.mark.asyncio
async def test_adaptive_runtime_shadow_mode(runtime):
    assert runtime.shadow_mode is True
    runtime.set_shadow_mode(False)
    assert runtime.shadow_mode is False


@pytest.mark.asyncio
async def test_adaptive_runtime_no_candidates(runtime):
    task = MockTaskSignature(complexity="simple", ambiguity="clear", risk="low")
    user = UserStateSnapshot(user_id="u1", tenant_id="t1")
    prefs = ResolvedPreferences()
    behavior = BehaviorPatternSummary(user_id="u1", tenant_id="t1")
    capabilities = SystemCapabilitySnapshot()
    evidence = HistoricalEvidence()

    recs = await runtime.recommend(
        task_signature=task,
        user_state=user,
        resolved_preferences=prefs,
        behavior_patterns=behavior,
        system_capabilities=capabilities,
        historical_evidence=evidence,
    )
    assert len(recs.recommendations) >= 1
    assert recs.top_recommendation.action_type == AdaptiveActionType.RESPOND_DIRECTLY

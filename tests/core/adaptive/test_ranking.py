"""Tests for adaptive ranking."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    AdaptiveContext,
    BehaviorPatternSummary,
    HistoricalEvidence,
    ResolvedPreferences,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.ranking.baseline import RuleBasedAdaptivePolicy
from ai_karen_engine.core.adaptive.ranking.utility import ActionUtilityEstimator


class MockTaskSignature:
    def __init__(self, complexity="simple", ambiguity="clear", risk="low", tool_requirements=None, reasoning_requirements=None, collaboration_value=0.0, verification_value=0.0, memory_relevance=0.0):
        self.complexity = complexity
        self.ambiguity = ambiguity
        self.risk = risk
        self.tool_requirements = tool_requirements or []
        self.reasoning_requirements = reasoning_requirements or []
        self.collaboration_value = collaboration_value
        self.verification_value = verification_value
        self.memory_relevance = memory_relevance


@pytest.fixture
def context():
    task = MockTaskSignature(complexity="moderate", ambiguity="clear", risk="low")
    user = UserStateSnapshot(user_id="u1", tenant_id="t1")
    prefs = ResolvedPreferences()
    behavior = BehaviorPatternSummary(user_id="u1", tenant_id="t1")
    capabilities = SystemCapabilitySnapshot(
        available_tools=["github", "filesystem"],
        available_agents=["analyst"],
        available_workflows=["multi_step_pipeline"],
    )
    evidence = HistoricalEvidence()
    return AdaptiveContext(
        request_id="req1",
        correlation_id="corr1",
        task_signature=task,
        user_state=user,
        resolved_preferences=prefs,
        behavior_patterns=behavior,
        system_capabilities=capabilities,
        historical_evidence=evidence,
    )


def test_utility_estimator_respond_directly(context):
    estimator = ActionUtilityEstimator()
    components = estimator.estimate(
        action_type=AdaptiveActionType.RESPOND_DIRECTLY,
        target_id=None,
        context={"task_signature": context.task_signature, "resolved_preferences": context.resolved_preferences},
    )
    assert 0.0 <= components.utility <= 1.0


def test_utility_estimator_use_tool(context):
    estimator = ActionUtilityEstimator()
    components = estimator.estimate(
        action_type=AdaptiveActionType.USE_TOOL,
        target_id="github",
        context={"task_signature": context.task_signature, "resolved_preferences": context.resolved_preferences},
    )
    assert components.task_fit > 0.0


def test_baseline_rank(context):
    policy = RuleBasedAdaptivePolicy()
    candidates = [
        {"action_type": AdaptiveActionType.RESPOND_DIRECTLY, "target_id": None},
        {"action_type": AdaptiveActionType.USE_TOOL, "target_id": "github"},
        {"action_type": AdaptiveActionType.ASK_CLARIFICATION, "target_id": None},
    ]
    recs = policy.rank(context, candidates)
    assert len(recs.recommendations) == 3
    assert recs.recommendations[0].utility_score >= recs.recommendations[-1].utility_score


def test_baseline_explainability(context):
    policy = RuleBasedAdaptivePolicy()
    candidates = [
        {"action_type": AdaptiveActionType.RESPOND_DIRECTLY, "target_id": None},
    ]
    recs = policy.rank(context, candidates)
    assert len(recs.recommendations[0].explanation_codes) > 0
    assert recs.recommendations[0].score_components is not None

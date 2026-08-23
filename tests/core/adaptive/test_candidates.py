"""Tests for adaptive candidates."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.candidates.catalog import AdaptiveActionCatalog
from ai_karen_engine.core.adaptive.candidates.filters import (
    CandidateFilterResult,
    HardConstraintFilter,
)
from ai_karen_engine.core.adaptive.candidates.generator import ActionCandidateGenerator
from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    ResolvedPreferences,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)


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


def test_action_catalog_defaults():
    defaults = AdaptiveActionCatalog.default_candidates()
    assert AdaptiveActionType.RESPOND_DIRECTLY in defaults
    assert AdaptiveActionType.RETRIEVE_MEMORY in defaults


def test_candidate_generator_simple():
    generator = ActionCandidateGenerator(
        system_capabilities=SystemCapabilitySnapshot(
            available_tools=["github"],
            available_agents=["analyst"],
        )
    )
    task = MockTaskSignature(complexity="simple", ambiguity="clear")
    user = UserStateSnapshot(user_id="u1")
    candidates = generator.generate(task, user)
    action_types = [c["action_type"] for c in candidates]
    assert AdaptiveActionType.RESPOND_DIRECTLY in action_types
    assert AdaptiveActionType.RETRIEVE_MEMORY in action_types


def test_candidate_generator_tool_requirement():
    generator = ActionCandidateGenerator(
        system_capabilities=SystemCapabilitySnapshot(
            available_tools=["github", "filesystem"],
        )
    )
    task = MockTaskSignature(tool_requirements=["github"])
    user = UserStateSnapshot(user_id="u1")
    candidates = generator.generate(task, user)
    tool_candidates = [c for c in candidates if c["action_type"] == AdaptiveActionType.USE_TOOL]
    assert len(tool_candidates) == 1
    assert tool_candidates[0]["target_id"] == "github"


def test_candidate_generator_multi_agent():
    generator = ActionCandidateGenerator(
        system_capabilities=SystemCapabilitySnapshot(
            available_agents=["a1", "a2"],
        )
    )
    task = MockTaskSignature(collaboration_value=0.7, verification_value=0.4)
    user = UserStateSnapshot(user_id="u1")
    candidates = generator.generate(task, user)
    ma_candidates = [c for c in candidates if c["action_type"] == AdaptiveActionType.USE_MULTI_AGENT]
    assert len(ma_candidates) == 1


def test_hard_constraint_filter_local_only():
    filt = HardConstraintFilter(
        system_capabilities=SystemCapabilitySnapshot(local_only_mode=True)
    )
    candidates = [
        {"action_type": AdaptiveActionType.USE_TOOL, "target_id": "cloud_search"},
        {"action_type": AdaptiveActionType.RESPOND_DIRECTLY, "target_id": None},
    ]
    filtered = filt.filter(candidates, context={"local_only": True})
    assert all(c["filter_result"] != CandidateFilterResult.INELIGIBLE for c in filtered)


def test_hard_constraint_filter_forbidden_action():
    filt = HardConstraintFilter(
        resolved_preferences=ResolvedPreferences(
            forbidden_action_types=["use_tool"]
        )
    )
    candidates = [
        {"action_type": AdaptiveActionType.USE_TOOL, "target_id": "github"},
        {"action_type": AdaptiveActionType.RESPOND_DIRECTLY, "target_id": None},
    ]
    filtered = filt.filter(candidates)
    assert all(c["action_type"] != AdaptiveActionType.USE_TOOL for c in filtered)

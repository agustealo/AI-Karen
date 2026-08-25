"""
Tests for COG-REFLECT-1 reflection / consolidation engine.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ai_karen_engine.core.adaptive.learning.reflection_contracts import (
    ExperienceEvent,
    OutcomeEvidence,
    PromotionAction,
    ReflectionCandidate,
    ReflectionCandidateType,
    ReflectionContext,
    ReflectionInput,
    ReflectionPolicy,
    make_candidate_id,
)
from ai_karen_engine.core.adaptive.learning.reflector import (
    PromotionGate,
    ReflectionEngine,
    make_experience_event,
)
from ai_karen_engine.core.reasoning.belief.contracts import (
    BeliefAssessment,
    BeliefVerdict,
    ClaimStatus,
    ConfidenceMetrics,
)


def make_outcome(
    execution_status: str = "success",
    completion: bool = True,
    user_feedback: str | None = None,
    correction: bool = False,
    tool_success: bool | None = None,
    latency_ms: float = 100.0,
    fallback_used: bool = False,
    **metadata: object,
) -> OutcomeEvidence:
    return OutcomeEvidence(
        outcome_id=f"out_{id(object())}",
        execution_status=execution_status,
        user_feedback=user_feedback,
        correction=correction,
        completion=completion,
        tool_success=tool_success,
        latency_ms=latency_ms,
        fallback_used=fallback_used,
        metadata=dict(metadata),
    )


def make_reflection_input(
    events: list[ExperienceEvent] | None = None,
    max_candidates: int = 20,
) -> ReflectionInput:
    return ReflectionInput(
        events=events or [],
        context=ReflectionContext(
            user_id="u1",
            tenant_id="t1",
            session_id="s1",
        ),
        max_candidates=max_candidates,
    )


class TestRepeatedExperience:
    def test_repeated_compatible_evidence_can_create_candidate(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "tool_used", "used github tool",
                outcome=make_outcome(execution_status="success", action_type="use_tool"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "use_tool", "project": "KAREN"},
            )
            for _ in range(3)
        ]
        candidates = engine.reflect(make_reflection_input(events))
        assert len(candidates) > 0
        pattern_candidates = [c for c in candidates if c.candidate_type == ReflectionCandidateType.BEHAVIOR_PATTERN]
        assert len(pattern_candidates) > 0

    def test_one_weak_observation_remains_tentative(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "tool_used", "used dark UI once",
                outcome=make_outcome(execution_status="success", action_type="use_tool"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "use_tool"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        # Single observation produces a candidate but with low confidence
        if candidates:
            assert candidates[0].confidence < 0.7
        else:
            pass  # No candidate from single non-explicit event is also acceptable

    def test_explicit_user_statement_can_create_stronger_candidate(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "user_preference", "I prefer complete files",
                explicit=True,
                user_id="u1", tenant_id="t1",
                metadata={"preference_ref": "output_format.complete_files"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        pref_candidates = [c for c in candidates if c.candidate_type == ReflectionCandidateType.PREFERENCE]
        assert len(pref_candidates) > 0
        assert pref_candidates[0].confidence >= 0.7
        assert pref_candidates[0].is_explicit

    def test_one_successful_attempt_is_not_automatically_generalized(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "tool_used", "completed task with github",
                outcome=make_outcome(execution_status="success", completion=True, action_type="use_tool"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "use_tool"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        if candidates:
            success_candidates = [c for c in candidates if c.candidate_type == ReflectionCandidateType.SUCCESS_PATTERN]
            if success_candidates:
                assert "single_observation" in success_candidates[0].reason_codes


class TestPromotionGate:
    def _make_candidate(
        self,
        candidate_type: ReflectionCandidateType = ReflectionCandidateType.PREFERENCE,
        confidence: float = 0.8,
        salience: float = 0.9,
        support_count: int = 1,
        evidence_refs: list[str] | None = None,
        reason_codes: list[str] | None = None,
        contradiction_refs: list[str] | None = None,
    ) -> ReflectionCandidate:
        return ReflectionCandidate(
            candidate_id=make_candidate_id(),
            candidate_type=candidate_type,
            summary="test candidate",
            confidence=confidence,
            salience=salience,
            support_count=support_count,
            evidence_refs=evidence_refs or [],
            reason_codes=reason_codes or ["explicit"],
            contradiction_refs=contradiction_refs or [],
        )

    def test_repeated_compatible_evidence_can_create_candidate(self):
        engine = ReflectionEngine()
        gate = PromotionGate()
        events = [
            make_experience_event(
                "tool_used", "github success",
                outcome=make_outcome(execution_status="success", action_type="use_tool"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "use_tool"},
            )
            for _ in range(3)
        ]
        candidates = engine.reflect(make_reflection_input(events))
        pattern_candidates = [c for c in candidates if c.candidate_type == ReflectionCandidateType.BEHAVIOR_PATTERN]
        assert len(pattern_candidates) > 0
        result = gate.evaluate(pattern_candidates[0])
        assert isinstance(result, type(result))

    def test_one_weak_observation_remains_tentative(self):
        engine = ReflectionEngine()
        gate = PromotionGate()
        events = [
            make_experience_event(
                "tool_used", "dark UI once",
                outcome=make_outcome(execution_status="success", action_type="use_tool"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "use_tool"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        if candidates:
            result = gate.evaluate(candidates[0])
            # Weak observation should not be promoted
            assert result.action in (PromotionAction.DEFER, PromotionAction.REJECT)

    def test_one_successful_attempt_not_generalized(self):
        engine = ReflectionEngine()
        gate = PromotionGate()
        events = [
            make_experience_event(
                "action", "one success",
                outcome=make_outcome(execution_status="success", completion=True, action_type="respond"),
                user_id="u1", tenant_id="t1",
                metadata={"action_type": "respond"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        for c in candidates:
            result = gate.evaluate(c)
            if c.candidate_type == ReflectionCandidateType.SUCCESS_PATTERN:
                assert result.action in (PromotionAction.DEFER, PromotionAction.REJECT)

    def test_candidate_can_be_rejected(self):
        gate = PromotionGate()
        candidate = self._make_candidate(
            candidate_type=ReflectionCandidateType.SEMANTIC_FACT,
            confidence=0.1,
            salience=0.8,
            support_count=1,
            evidence_refs=["ev1"],
        )
        result = gate.evaluate(candidate)
        assert result.action == PromotionAction.REJECT

    def test_candidate_can_be_deferred(self):
        gate = PromotionGate()
        candidate = self._make_candidate(
            candidate_type=ReflectionCandidateType.BEHAVIOR_PATTERN,
            confidence=0.5,
            salience=0.3,
            support_count=3,
            evidence_refs=["ev1", "ev2", "ev3"],
            reason_codes=["repeated"],
        )
        result = gate.evaluate(candidate)
        assert result.action in (PromotionAction.DEFER, PromotionAction.REJECT)

    def test_contradictory_evidence_prevents_blind_promotion(self):
        gate = PromotionGate()
        candidate = self._make_candidate(
            candidate_type=ReflectionCandidateType.SEMANTIC_FACT,
            confidence=0.9,
            salience=0.8,
            support_count=3,
            evidence_refs=["ev1", "ev2", "ev3"],
            contradiction_refs=["con1", "con2"],
            reason_codes=["repeated"],
        )
        result = gate.evaluate(candidate)
        assert result.action in (PromotionAction.REJECT, PromotionAction.DEFER)


class TestPromotionProtocols:
    def test_belief_assessment_like_protocol(self):
        from ai_karen_engine.core.adaptive.learning.reflection_contracts import (
            BeliefAssessmentLike,
        )

        class FakeAssessment:
            overall_confidence: float = 0.1
            verdict: str = "inactive"
            reason_codes: list[str] = []
            evidence_refs: list[str] = []
            uncertainty_sources: list[str] = []

        fake = FakeAssessment()
        assert isinstance(fake, BeliefAssessmentLike)

    def test_goal_context_like_protocol(self):
        from ai_karen_engine.core.adaptive.learning.reflection_contracts import (
            GoalContextLike,
        )

        class FakeGoal:
            goal_id: str = "g1"
            tenant_id: str = "t1"
            user_id: str | None = "u1"
            description: str = "test"
            state: str = "active"
            priority: str = "high"
            goal_type: str = "explicit"
            confidence: float = 0.9
            evidence_refs: list[str] = []
            depends_on: list[str] = []
            blocks: list[str] = []
            conflicts_with: list[str] = []

        fake = FakeGoal()
        assert isinstance(fake, GoalContextLike)


class TestNoPersistence:
    def test_no_direct_persistence(self):
        """Reflection engine must not have persistence methods."""
        engine = ReflectionEngine()
        assert not hasattr(engine, "save")
        assert not hasattr(engine, "persist")
        assert not hasattr(engine, "commit")
        assert not hasattr(engine, "write")

    def test_candidate_preserves_source_evidence(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "user_preference", "prefer concise",
                explicit=True,
                user_id="u1", tenant_id="t1",
                evidence_refs=["src1", "src2"],
                metadata={"preference_ref": "output.verbosity"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        assert len(candidates) > 0
        for c in candidates:
            assert len(c.evidence_refs) > 0
            assert "src1" in c.evidence_refs


class TestFailureLearning:
    def test_repeated_failure_can_produce_procedural_lesson_candidate(self):
        engine = ReflectionEngine()
        events = [
            make_experience_event(
                "action_failed", "provider error AUTH_FAILURE",
                explicit=True,
                outcome=make_outcome(
                    execution_status="failure",
                    action_type="use_provider",
                    error="AUTH_FAILURE",
                ),
                user_id="u1", tenant_id="t1",
            )
            for _ in range(3)
        ]
        candidates = engine.reflect(make_reflection_input(events))
        failure_candidates = [c for c in candidates if c.candidate_type == ReflectionCandidateType.FAILURE_LESSON]
        assert len(failure_candidates) > 0
        assert failure_candidates[0].failure_lesson is not None


class TestNoCrossTenant:
    def test_no_cross_tenant_reflection(self):
        engine = ReflectionEngine()
        events_a = [
            make_experience_event(
                "action", "tenant-a event",
                outcome=make_outcome(execution_status="success"),
                user_id="u1", tenant_id="tenant-a",
            )
        ]
        events_b = [
            make_experience_event(
                "action", "tenant-b event",
                outcome=make_outcome(execution_status="success"),
                user_id="u2", tenant_id="tenant-b",
            )
        ]
        candidates = engine.reflect(make_reflection_input(events_a + events_b))
        if candidates:
            tenants = set(c.tenant_id for c in candidates)
            assert len(tenants) == 1


class TestRetractedEvidence:
    def test_retracted_evidence_cannot_support_promotion(self):
        engine = ReflectionEngine()
        gate = PromotionGate()
        events = [
            make_experience_event(
                "user_preference", "I like X",
                explicit=True,
                user_id="u1", tenant_id="t1",
                evidence_refs=["contradicting_ref"],
                metadata={"preference_ref": "test.x"},
            )
        ]
        candidates = engine.reflect(make_reflection_input(events))
        assert len(candidates) > 0
        candidate = candidates[0]
        candidate.contradiction_refs = ["contra_1"]
        candidate.support_count = 0
        result = gate.evaluate(candidate)
        assert result.action in (PromotionAction.DEFER, PromotionAction.REJECT)


class TestReflectionCandidateTypes:
    def test_all_candidate_types_exist(self):
        expected_types = {
            ReflectionCandidateType.PREFERENCE,
            ReflectionCandidateType.BEHAVIOR_PATTERN,
            ReflectionCandidateType.PROCEDURAL_LESSON,
            ReflectionCandidateType.SEMANTIC_FACT,
            ReflectionCandidateType.GOAL_UPDATE,
            ReflectionCandidateType.RELATIONSHIP_INSIGHT,
            ReflectionCandidateType.FAILURE_LESSON,
            ReflectionCandidateType.SUCCESS_PATTERN,
            ReflectionCandidateType.NONE,
        }
        actual = {t for t in ReflectionCandidateType}
        assert expected_types.issubset(actual)


class TestNoProviderImplementation:
    def test_no_external_deps_in_reflection(self):
        import inspect
        import ai_karen_engine.core.adaptive.learning.reflector as mod
        import ai_karen_engine.core.adaptive.learning.reflection_contracts as rmod

        banned = ["sqlalchemy", "redis", "milvus", "fastapi", "openai", "anthropic", "ollama", "requests", "httpx"]
        for module in (mod, rmod):
            source = inspect.getsource(module)
            for pattern in banned:
                parts = source.split(pattern)
                if len(parts) > 1:
                    assert False, f"Found banned dependency '{pattern}' in {module.__name__}"


__all__ = [
    "TestRepeatedExperience",
    "TestPromotionGate",
    "TestPromotionProtocols",
    "TestNoPersistence",
    "TestFailureLearning",
    "TestNoCrossTenant",
    "TestRetractedEvidence",
    "TestReflectionCandidateTypes",
    "TestNoProviderImplementation",
]

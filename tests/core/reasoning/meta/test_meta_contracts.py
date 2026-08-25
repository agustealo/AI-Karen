from __future__ import annotations

from ai_karen_engine.core.reasoning.meta.contracts import (
    BeliefConflictSummary,
    LoopAssessment,
    MemoryReliabilityAssessment,
    MetaCognitiveState,
    MetaReasonCode,
    MetaStatus,
    ReasoningDepth,
    ReasoningDepthRecommendation,
    StrategyFingerprint,
    VerificationNeedAssessment,
)


def test_meta_status_values():
    assert MetaStatus.STABLE.value == "stable"
    assert MetaStatus.LOOPING.value == "looping"


def test_meta_cognitive_state_defaults():
    state = MetaCognitiveState()
    assert state.knowledge_sufficiency == 0.0
    assert state.confidence == 0.0


def test_loop_assessment_creation():
    fp = StrategyFingerprint(strategy_type="causal", evidence_hash="e1", outcome_class="failure")
    loop = LoopAssessment(is_looping=True, loop_count=3, fingerprint=fp)
    assert loop.is_looping is True
    assert loop.fingerprint.strategy_type == "causal"


def test_memory_reliability_assessment():
    mra = MemoryReliabilityAssessment(recall_confidence=0.3, reliability=0.3)
    assert mra.recall_confidence == 0.3


def test_verification_need_assessment():
    vna = VerificationNeedAssessment(required=True, reason=MetaReasonCode.LOW_MEMORY_CONFIDENCE)
    assert vna.required is True


def test_reasoning_depth_recommendation():
    rec = ReasoningDepthRecommendation(recommended_depth=ReasoningDepth.DEEP)
    assert rec.recommended_depth == ReasoningDepth.DEEP


def test_belief_conflict_summary():
    cs = BeliefConflictSummary(conflict_id="c1", claim_a="a", claim_b="b", severity="high")
    assert cs.conflict_id == "c1"
    assert cs.severity == "high"

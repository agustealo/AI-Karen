from __future__ import annotations

from ai_karen_engine.core.reasoning.meta.assessment import MetaCognitiveAssessor
from ai_karen_engine.core.reasoning.meta.calibration import CalibrationTracker
from ai_karen_engine.core.reasoning.meta.contracts import (
    BeliefConflictSummary,
    CalibrationObservation,
    MetaCognitiveRequest,
    MetaReasonCode,
    MetaStatus,
    ReasoningDepth,
    StrategyAttempt,
)
from ai_karen_engine.core.reasoning.meta.loop_detection import LoopDetector
from ai_karen_engine.core.reasoning.meta.verification import MetaVerificationEngine


def test_low_memory_confidence_produces_weak_memory_signal():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", memory_reliability=0.2, reasoning_confidence=0.8)
    result = assessor.assess(req)
    assert MetaReasonCode.LOW_MEMORY_CONFIDENCE in result.assessment.reason_codes


def test_conflicting_evidence_produces_conflict_signal():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(
        request_id="r1",
        correlation_id="c1",
        reasoning_confidence=0.8,
        belief_conflicts=[BeliefConflictSummary(conflict_id="cf1", claim_a="a", claim_b="b")],
    )
    result = assessor.assess(req)
    assert MetaReasonCode.CONFLICTING_EVIDENCE in result.assessment.reason_codes
    assert result.assessment.status == MetaStatus.CONFLICTED


def test_stale_memory_can_trigger_verification():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", memory_reliability=0.2, reasoning_confidence=0.5)
    result = assessor.assess(req)
    assert result.verification_need is not None
    assert result.verification_need.required is True


def test_high_risk_uncertain_claim_requires_verification():
    engine = MetaVerificationEngine()
    state = type("S", (), {"evidence_consistency": 0.8, "reasoning_confidence": 0.9})()
    req = engine.assess(state, confidence=0.2, risk=0.8, freshness=0.5)
    assert req.required is True


def test_repeated_failed_strategy_can_produce_looping():
    detector = LoopDetector()
    attempts = [
        StrategyAttempt(strategy_id="s1", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
        StrategyAttempt(strategy_id="s2", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
        StrategyAttempt(strategy_id="s3", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
    ]
    result = detector.detect(attempts)
    assert result.is_looping is True


def test_loop_detection_recommends_strategy_change():
    detector = LoopDetector()
    attempts = [
        StrategyAttempt(strategy_id="s1", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
        StrategyAttempt(strategy_id="s2", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
        StrategyAttempt(strategy_id="s3", strategy_type="causal", evidence_hashes=["e1"], outcome="failure"),
    ]
    result = detector.detect(attempts)
    assert detector.recommend_action(result) == "change_strategy"


def test_sufficient_evidence_can_recommend_stopping():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", reasoning_confidence=0.9, budget_remaining={"reasoning_steps": 0})
    result = assessor.assess(req)
    assert MetaReasonCode.BUDGET_EXHAUSTED in result.assessment.reason_codes
    assert "stop" in result.assessment.recommended_cognitive_actions


def test_meta_layer_can_recommend_deeper_reasoning():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", reasoning_confidence=0.1)
    result = assessor.assess(req)
    assert result.depth_recommendation is not None
    assert result.depth_recommendation.recommended_depth == ReasoningDepth.DEEP


def test_meta_layer_cannot_execute_tools():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1")
    result = assessor.assess(req)
    assert not hasattr(result, "execute")


def test_uncertainty_remains_distinct_from_failure():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", reasoning_confidence=0.4)
    result = assessor.assess(req)
    assert result.assessment.status != MetaStatus.FAILED


def test_degraded_memory_runtime_signals_remain_explicit():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(request_id="r1", correlation_id="c1", memory_reliability=0.1)
    result = assessor.assess(req)
    assert result.memory_reliability is not None
    assert MetaReasonCode.LOW_MEMORY_CONFIDENCE in result.memory_reliability.reason_codes


def test_reason_codes_explain_every_recommendation():
    assessor = MetaCognitiveAssessor()
    req = MetaCognitiveRequest(
        request_id="r1",
        correlation_id="c1",
        reasoning_confidence=0.2,
        belief_conflicts=[BeliefConflictSummary(conflict_id="cf1", claim_a="a", claim_b="b")],
    )
    result = assessor.assess(req)
    for action in result.assessment.recommended_cognitive_actions:
        assert len(result.assessment.reason_codes) > 0


def test_calibration_tracker_accuracy():
    tracker = CalibrationTracker()
    tracker.record(CalibrationObservation(predicted_confidence=0.9, correction_required=False))
    tracker.record(CalibrationObservation(predicted_confidence=0.5, correction_required=True))
    assert tracker.accuracy() == 0.5

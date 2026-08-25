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

TENANT = "tenant-test"


def _request(**kwargs) -> MetaCognitiveRequest:
    return MetaCognitiveRequest(
        request_id=kwargs.pop("request_id", "r1"),
        correlation_id=kwargs.pop("correlation_id", "c1"),
        tenant_id=kwargs.pop("tenant_id", TENANT),
        **kwargs,
    )


def test_low_memory_confidence_produces_weak_memory_signal():
    result = MetaCognitiveAssessor().assess(
        _request(memory_reliability=0.2, reasoning_confidence=0.8)
    )
    assert MetaReasonCode.LOW_MEMORY_CONFIDENCE in result.assessment.reason_codes


def test_conflicting_evidence_produces_conflict_signal():
    result = MetaCognitiveAssessor().assess(
        _request(
            reasoning_confidence=0.8,
            belief_conflicts=[
                BeliefConflictSummary(conflict_id="cf1", claim_a="a", claim_b="b")
            ],
        )
    )
    assert MetaReasonCode.EVIDENCE_INCONSISTENT in result.assessment.reason_codes
    assert result.assessment.status == MetaStatus.CONFLICTED


def test_stale_memory_can_trigger_verification():
    result = MetaCognitiveAssessor().assess(
        _request(memory_reliability=0.2, reasoning_confidence=0.5)
    )
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
        StrategyAttempt(
            strategy_id="s1",
            strategy_type="causal",
            evidence_hashes=["e1"],
            outcome="failure",
        ),
        StrategyAttempt(
            strategy_id="s2",
            strategy_type="causal",
            evidence_hashes=["e1"],
            outcome="failure",
        ),
        StrategyAttempt(
            strategy_id="s3",
            strategy_type="causal",
            evidence_hashes=["e1"],
            outcome="failure",
        ),
    ]
    assert detector.detect(attempts).is_looping is True


def test_loop_detection_recommends_strategy_change():
    detector = LoopDetector()
    attempts = [
        StrategyAttempt(
            strategy_id=f"s{i}",
            strategy_type="causal",
            evidence_hashes=["e1"],
            outcome="failure",
        )
        for i in range(1, 4)
    ]
    result = detector.detect(attempts)
    assert detector.recommend_action(result) == "change_strategy"


def test_sufficient_evidence_can_recommend_stopping():
    result = MetaCognitiveAssessor().assess(
        _request(reasoning_confidence=0.9, budget_remaining={"reasoning_steps": 0})
    )
    assert MetaReasonCode.BUDGET_EXHAUSTED in result.assessment.reason_codes
    assert "stop" in result.assessment.recommended_cognitive_actions


def test_meta_layer_can_recommend_deeper_reasoning():
    result = MetaCognitiveAssessor().assess(_request(reasoning_confidence=0.1))
    assert result.depth_recommendation is not None
    assert result.depth_recommendation.recommended_depth == ReasoningDepth.DEEP


def test_meta_layer_cannot_execute_tools():
    result = MetaCognitiveAssessor().assess(_request())
    assert not hasattr(result, "execute")


def test_uncertainty_remains_distinct_from_failure():
    result = MetaCognitiveAssessor().assess(_request(reasoning_confidence=0.4))
    assert result.assessment.status != MetaStatus.FAILED


def test_degraded_memory_runtime_signals_remain_explicit():
    result = MetaCognitiveAssessor().assess(_request(memory_reliability=0.1))
    assert result.memory_reliability is not None
    assert MetaReasonCode.LOW_MEMORY_CONFIDENCE in result.memory_reliability.reason_codes


def test_reason_codes_explain_every_recommendation():
    result = MetaCognitiveAssessor().assess(
        _request(
            reasoning_confidence=0.2,
            belief_conflicts=[
                BeliefConflictSummary(conflict_id="cf1", claim_a="a", claim_b="b")
            ],
        )
    )
    for _action in result.assessment.recommended_cognitive_actions:
        assert result.assessment.reason_codes


def test_calibration_tracker_accuracy():
    tracker = CalibrationTracker()
    tracker.record(
        CalibrationObservation(predicted_confidence=0.9, correction_required=False)
    )
    tracker.record(
        CalibrationObservation(predicted_confidence=0.5, correction_required=True)
    )
    assert tracker.accuracy() == 0.5

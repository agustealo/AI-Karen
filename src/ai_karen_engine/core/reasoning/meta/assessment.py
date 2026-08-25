from __future__ import annotations

import hashlib
import logging

from ai_karen_engine.core.reasoning.meta.contracts import (
    CalibrationObservation,
    LoopAssessment,
    MemoryReliabilityAssessment,
    MetaAssessment,
    MetaCognitiveRequest,
    MetaCognitiveResult,
    MetaCognitiveState,
    MetaReasonCode,
    MetaStatus,
    ReasoningDepth,
    ReasoningDepthRecommendation,
    StrategyAttempt,
    StrategyFingerprint,
    VerificationNeedAssessment,
)

logger = logging.getLogger(__name__)


class MetaCognitiveAssessor:
    """Assesses the quality of the current cognitive state."""

    def assess(self, request: MetaCognitiveRequest) -> MetaCognitiveResult:
        state = MetaCognitiveState()
        issues: list[str] = []
        actions: list[str] = []
        reason_codes: list[MetaReasonCode] = []

        state.reasoning_confidence = request.reasoning_confidence
        state.memory_reliability = request.memory_reliability
        state.evidence_consistency = max(0.0, 1.0 - (len(request.belief_conflicts) * 0.2))

        if request.memory_reliability < 0.4:
            reason_codes.append(MetaReasonCode.LOW_MEMORY_CONFIDENCE)
            issues.append("low_memory_confidence")
            actions.append("verify_memory")

        if request.belief_conflicts:
            reason_codes.append(MetaReasonCode.CONFLICTING_EVIDENCE)
            issues.append("conflicting_evidence")
            actions.append("resolve_conflict")

        loop = self._detect_loop(request.strategy_attempts)
        if loop and loop.is_looping:
            reason_codes.append(MetaReasonCode.LOOP_DETECTED)
            issues.append("reasoning_loop")
            actions.append("change_strategy")

        if request.reasoning_confidence < 0.3:
            reason_codes.append(MetaReasonCode.LOW_MEMORY_CONFIDENCE)
            issues.append("low_reasoning_confidence")
            actions.append("deepen_reasoning")

        budget = request.budget_remaining.get("reasoning_steps", 5)
        if budget <= 1:
            reason_codes.append(MetaReasonCode.BUDGET_EXHAUSTED)
            issues.append("budget_exhausted")
            actions.append("stop")

        status = self._derive_status(reason_codes)
        confidence = (request.reasoning_confidence + request.memory_reliability + state.evidence_consistency) / 3.0

        assessment = MetaAssessment(
            status=status,
            confidence=confidence,
            issues=issues,
            recommended_cognitive_actions=actions,
            reason_codes=reason_codes,
        )

        state.reason_codes = reason_codes
        state.confidence = confidence

        memory_reliability = self._assess_memory_reliability(request)
        verification_need = self._assess_verification_need(state, request)
        depth_rec = self._assess_depth(state, request)
        calibration = [CalibrationObservation(predicted_confidence=request.reasoning_confidence)]

        return MetaCognitiveResult(
            assessment=assessment,
            state=state,
            loop_assessment=loop,
            memory_reliability=memory_reliability,
            verification_need=verification_need,
            depth_recommendation=depth_rec,
            calibration_observations=calibration,
        )

    def _derive_status(self, reason_codes: list[MetaReasonCode]) -> MetaStatus:
        if MetaReasonCode.LOOP_DETECTED in reason_codes:
            return MetaStatus.LOOPING
        if MetaReasonCode.CONFLICTING_EVIDENCE in reason_codes:
            return MetaStatus.CONFLICTED
        if MetaReasonCode.INSUFFICIENT_EVIDENCE in reason_codes:
            return MetaStatus.INSUFFICIENT
        if MetaReasonCode.LOW_MEMORY_CONFIDENCE in reason_codes:
            return MetaStatus.STALE
        if MetaReasonCode.BUDGET_EXHAUSTED in reason_codes:
            return MetaStatus.DEGRADED
        return MetaStatus.STABLE

    def _detect_loop(self, attempts: list[StrategyAttempt]) -> LoopAssessment | None:
        if len(attempts) < 3:
            return None
        fingerprints = []
        for a in attempts:
            evidence_hash = hashlib.sha256("|".join(a.evidence_hashes).encode()).hexdigest()[:16]
            fingerprints.append(StrategyFingerprint(
                strategy_type=a.strategy_type,
                evidence_hash=evidence_hash,
                outcome_class=a.outcome,
            ))
        if len(fingerprints) >= 3:
            first = fingerprints[-3]
            if all(f.strategy_type == first.strategy_type and f.evidence_hash == first.evidence_hash for f in fingerprints[-3:]):
                return LoopAssessment(is_looping=True, loop_count=3, fingerprint=first)
        return None

    def _assess_memory_reliability(self, request: MetaCognitiveRequest) -> MemoryReliabilityAssessment:
        return MemoryReliabilityAssessment(
            recall_confidence=request.memory_reliability,
            reliability=request.memory_reliability,
            reason_codes=[MetaReasonCode.LOW_MEMORY_CONFIDENCE] if request.memory_reliability < 0.4 else [],
        )

    def _assess_verification_need(self, state: MetaCognitiveState, request: MetaCognitiveRequest) -> VerificationNeedAssessment:
        if state.memory_reliability < 0.3 or state.reasoning_confidence < 0.3 or state.evidence_consistency < 0.3:
            return VerificationNeedAssessment(required=True, reason=MetaReasonCode.LOW_MEMORY_CONFIDENCE, depth=ReasoningDepth.STANDARD, urgency=0.8)
        return VerificationNeedAssessment(required=False)

    def _assess_depth(self, state: MetaCognitiveState, request: MetaCognitiveRequest) -> ReasoningDepthRecommendation:
        if state.reasoning_confidence < 0.3:
            return ReasoningDepthRecommendation(recommended_depth=ReasoningDepth.DEEP, reason=MetaReasonCode.LOW_MEMORY_CONFIDENCE)
        if state.evidence_consistency < 0.4:
            return ReasoningDepthRecommendation(recommended_depth=ReasoningDepth.DEEP, reason=MetaReasonCode.CONFLICTING_EVIDENCE)
        return ReasoningDepthRecommendation(recommended_depth=ReasoningDepth.STANDARD)

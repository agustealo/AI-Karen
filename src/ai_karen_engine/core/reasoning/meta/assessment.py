from __future__ import annotations

import hashlib
import logging

from ai_karen_engine.core.contracts.cognitive import MetaConfidence, RetrievalConfidence
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
        state.memory_reliability = RetrievalConfidence(request.memory_reliability)
        state.evidence_consistency = self._compute_evidence_consistency(request.belief_conflicts)

        if request.memory_reliability < 0.4:
            reason_codes.append(MetaReasonCode.LOW_MEMORY_CONFIDENCE)
            issues.append("low_memory_confidence")
            actions.append("verify_memory")

        if request.belief_conflicts:
            reason_codes.append(MetaReasonCode.EVIDENCE_INCONSISTENT)
            issues.append("evidence_inconsistent")
            actions.append("resolve_conflict")

        loop = self._detect_loop(request.strategy_attempts)
        if loop and loop.is_looping:
            reason_codes.append(MetaReasonCode.LOOP_DETECTED)
            issues.append("reasoning_loop")
            actions.append("change_strategy")

        if request.reasoning_confidence < 0.3:
            reason_codes.append(MetaReasonCode.LOW_REASONING_CONFIDENCE)
            issues.append("low_reasoning_confidence")
            actions.append("deepen_reasoning")

        budget = request.budget_remaining.get("reasoning_steps", 5)
        if budget <= 1:
            reason_codes.append(MetaReasonCode.BUDGET_EXHAUSTED)
            issues.append("budget_exhausted")
            actions.append("stop")

        status = self._derive_status(reason_codes)
        confidence_value = (
            request.reasoning_confidence
            + request.memory_reliability
            + state.evidence_consistency
        ) / 3.0
        meta_confidence = MetaConfidence(confidence_value)

        assessment = MetaAssessment(
            status=status,
            confidence=meta_confidence,
            issues=issues,
            recommended_cognitive_actions=actions,
            reason_codes=reason_codes,
        )
        state.reason_codes = reason_codes
        state.confidence = meta_confidence

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
        if any(
            code in reason_codes
            for code in (MetaReasonCode.EVIDENCE_INCONSISTENT, MetaReasonCode.CONFLICTING_EVIDENCE)
        ):
            return MetaStatus.CONFLICTED
        if MetaReasonCode.INSUFFICIENT_EVIDENCE in reason_codes:
            return MetaStatus.INSUFFICIENT
        if MetaReasonCode.LOW_MEMORY_CONFIDENCE in reason_codes:
            return MetaStatus.STALE
        if MetaReasonCode.LOW_REASONING_CONFIDENCE in reason_codes:
            return MetaStatus.UNCERTAIN
        if MetaReasonCode.BUDGET_EXHAUSTED in reason_codes:
            return MetaStatus.DEGRADED
        return MetaStatus.STABLE

    def _compute_evidence_consistency(self, belief_conflicts: list) -> float:
        if not belief_conflicts:
            return 1.0
        severity_penalty = {"low": 0.2, "medium": 0.35, "high": 0.5, "critical": 0.8}
        penalty = sum(
            severity_penalty.get(getattr(conflict, "severity", "medium"), 0.35)
            for conflict in belief_conflicts
        )
        return max(0.0, 1.0 - penalty)

    def _detect_loop(self, attempts: list[StrategyAttempt]) -> LoopAssessment | None:
        if len(attempts) < 3:
            return None
        fingerprints: list[StrategyFingerprint] = []
        for attempt in attempts:
            evidence_hash = hashlib.sha256("|".join(attempt.evidence_hashes).encode()).hexdigest()[:16]
            fingerprints.append(
                StrategyFingerprint(
                    strategy_type=attempt.strategy_type,
                    evidence_hash=evidence_hash,
                    outcome_class=attempt.outcome,
                )
            )
        first = fingerprints[-3]
        if all(
            item.strategy_type == first.strategy_type
            and item.evidence_hash == first.evidence_hash
            and item.outcome_class == first.outcome_class
            for item in fingerprints[-3:]
        ):
            return LoopAssessment(is_looping=True, loop_count=3, fingerprint=first)
        return None

    def _assess_memory_reliability(
        self,
        request: MetaCognitiveRequest,
    ) -> MemoryReliabilityAssessment:
        confidence = RetrievalConfidence(request.memory_reliability)
        return MemoryReliabilityAssessment(
            recall_confidence=confidence,
            reliability=confidence,
            reason_codes=(
                [MetaReasonCode.LOW_MEMORY_CONFIDENCE]
                if request.memory_reliability < 0.4
                else []
            ),
        )

    def _assess_verification_need(
        self,
        state: MetaCognitiveState,
        request: MetaCognitiveRequest,
    ) -> VerificationNeedAssessment:
        if float(state.memory_reliability) < 0.3:
            return VerificationNeedAssessment(
                required=True,
                reason=MetaReasonCode.LOW_MEMORY_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="meta",
            )
        if state.reasoning_confidence < 0.3:
            return VerificationNeedAssessment(
                required=True,
                reason=MetaReasonCode.LOW_REASONING_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="meta",
            )
        if state.evidence_consistency < 0.3:
            return VerificationNeedAssessment(
                required=True,
                reason=MetaReasonCode.EVIDENCE_INCONSISTENT,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source="meta",
            )
        return VerificationNeedAssessment(required=False, source="meta")

    def _assess_depth(
        self,
        state: MetaCognitiveState,
        request: MetaCognitiveRequest,
    ) -> ReasoningDepthRecommendation:
        if state.reasoning_confidence < 0.3:
            return ReasoningDepthRecommendation(
                recommended_depth=ReasoningDepth.DEEP,
                reason=MetaReasonCode.LOW_REASONING_CONFIDENCE,
                confidence=MetaConfidence(0.8),
            )
        if state.evidence_consistency < 0.4:
            return ReasoningDepthRecommendation(
                recommended_depth=ReasoningDepth.DEEP,
                reason=MetaReasonCode.EVIDENCE_INCONSISTENT,
                confidence=MetaConfidence(0.8),
            )
        return ReasoningDepthRecommendation(
            recommended_depth=ReasoningDepth.STANDARD,
            confidence=MetaConfidence(0.7),
        )

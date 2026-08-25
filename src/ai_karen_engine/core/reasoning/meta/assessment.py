from __future__ import annotations

import hashlib

from ai_karen_engine.core.contracts.cognitive import (
    ReasoningDepth,
    VerificationReason,
    VerificationRequirement,
)
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
    ReasoningDepthRecommendation,
    StrategyAttempt,
    StrategyFingerprint,
)
from ai_karen_engine.core.reasoning.meta.policy import CognitivePolicyConfig


class MetaCognitiveAssessor:
    """Assess cognitive quality and recommend, but never execute, recovery."""

    def __init__(self, policy: CognitivePolicyConfig | None = None) -> None:
        self.policy = policy or CognitivePolicyConfig()

    def assess(self, request: MetaCognitiveRequest) -> MetaCognitiveResult:
        thresholds = self.policy.thresholds
        state = MetaCognitiveState()
        issues: list[str] = []
        actions: list[str] = []
        reason_codes: list[MetaReasonCode] = []

        state.reasoning_confidence = request.reasoning_confidence
        state.memory_reliability = request.memory_reliability
        state.evidence_consistency = self._compute_evidence_consistency(request.belief_conflicts)

        if thresholds.is_memory_weak(request.memory_reliability):
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

        if thresholds.is_reasoning_weak(request.reasoning_confidence):
            reason_codes.append(MetaReasonCode.LOW_REASONING_CONFIDENCE)
            issues.append("low_reasoning_confidence")
            actions.append("deepen_reasoning")

        budget = int(request.budget_remaining.get("reasoning_steps", 5))
        if not thresholds.has_budget_remaining(budget):
            reason_codes.append(MetaReasonCode.BUDGET_EXHAUSTED)
            issues.append("budget_exhausted")
            actions.append("stop")

        status = self._derive_status(reason_codes)
        confidence = max(
            0.0,
            min(
                1.0,
                (
                    request.reasoning_confidence
                    + request.memory_reliability
                    + state.evidence_consistency
                )
                / 3.0,
            ),
        )

        assessment = MetaAssessment(
            status=status,
            confidence=confidence,
            issues=issues,
            recommended_cognitive_actions=actions,
            reason_codes=reason_codes,
            policy_version=self.policy.policy_version,
            schema_version=self.policy.schema_version,
        )
        state.reason_codes = reason_codes
        state.confidence = confidence

        return MetaCognitiveResult(
            assessment=assessment,
            state=state,
            loop_assessment=loop,
            memory_reliability=self._assess_memory_reliability(request),
            verification_need=self._assess_verification_need(state),
            depth_recommendation=self._assess_depth(state),
            calibration_observations=[
                CalibrationObservation(predicted_confidence=request.reasoning_confidence)
            ]
            if self.policy.enable_calibration
            else [],
        )

    def _derive_status(self, reason_codes: list[MetaReasonCode]) -> MetaStatus:
        if MetaReasonCode.LOOP_DETECTED in reason_codes:
            return MetaStatus.LOOPING
        if MetaReasonCode.EVIDENCE_INCONSISTENT in reason_codes:
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

    def _compute_evidence_consistency(self, conflicts: list) -> float:
        if not conflicts:
            return 1.0
        severity_penalty = {
            "low": 0.10,
            "medium": 0.20,
            "high": 0.35,
            "critical": 0.50,
        }
        penalty = 0.0
        for conflict in conflicts:
            severity = str(getattr(conflict, "severity", "medium")).lower()
            penalty += severity_penalty.get(severity, 0.20)
        return max(0.0, 1.0 - penalty)

    def _detect_loop(self, attempts: list[StrategyAttempt]) -> LoopAssessment | None:
        threshold = self.policy.thresholds.loop_repeat_threshold
        if not self.policy.enable_loop_detection or len(attempts) < threshold:
            return None

        fingerprints: list[StrategyFingerprint] = []
        for attempt in attempts:
            evidence_hash = hashlib.sha256(
                "|".join(attempt.evidence_hashes).encode()
            ).hexdigest()[:16]
            fingerprints.append(
                StrategyFingerprint(
                    strategy_type=attempt.strategy_type,
                    evidence_hash=evidence_hash,
                    outcome_class=attempt.outcome,
                )
            )

        recent = fingerprints[-threshold:]
        first = recent[0]
        if all(
            fingerprint.strategy_type == first.strategy_type
            and fingerprint.evidence_hash == first.evidence_hash
            and fingerprint.outcome_class == first.outcome_class
            for fingerprint in recent
        ):
            return LoopAssessment(
                is_looping=True,
                loop_count=threshold,
                fingerprint=first,
            )
        return None

    def _assess_memory_reliability(
        self,
        request: MetaCognitiveRequest,
    ) -> MemoryReliabilityAssessment:
        weak = self.policy.thresholds.is_memory_weak(request.memory_reliability)
        return MemoryReliabilityAssessment(
            recall_confidence=request.memory_reliability,
            reliability=request.memory_reliability,
            reason_codes=[MetaReasonCode.LOW_MEMORY_CONFIDENCE] if weak else [],
        )

    def _assess_verification_need(
        self,
        state: MetaCognitiveState,
    ) -> VerificationRequirement:
        thresholds = self.policy.thresholds
        if state.memory_reliability < thresholds.verification_threshold:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_MEMORY_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source_stage="meta",
            )
        if state.reasoning_confidence < thresholds.verification_threshold:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.LOW_REASONING_CONFIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source_stage="meta",
            )
        if state.evidence_consistency < thresholds.weak_evidence_threshold:
            return VerificationRequirement(
                required=True,
                reason=VerificationReason.CONFLICTING_EVIDENCE,
                depth=ReasoningDepth.STANDARD,
                urgency=0.8,
                source_stage="meta",
            )
        return VerificationRequirement(required=False, source_stage="meta")

    def _assess_depth(
        self,
        state: MetaCognitiveState,
    ) -> ReasoningDepthRecommendation:
        thresholds = self.policy.thresholds
        if thresholds.should_deepen_reasoning(state.reasoning_confidence):
            return ReasoningDepthRecommendation(
                recommended_depth=ReasoningDepth.DEEP,
                reason=MetaReasonCode.LOW_REASONING_CONFIDENCE,
            )
        if state.evidence_consistency < thresholds.weak_evidence_threshold:
            return ReasoningDepthRecommendation(
                recommended_depth=ReasoningDepth.DEEP,
                reason=MetaReasonCode.EVIDENCE_INCONSISTENT,
            )
        return ReasoningDepthRecommendation(recommended_depth=ReasoningDepth.STANDARD)

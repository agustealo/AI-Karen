from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorSelectionContext,
    BehaviorType,
    VerificationDepth,
    VerificationReason,
    VerificationRequirement,
)


class VerificationDecider:
    """Determines verification requirements for behavior decisions."""

    def decide(self, context: BehaviorSelectionContext, candidate: BehaviorCandidate) -> VerificationRequirement:
        """Decide if verification is required."""
        if candidate.behavior_type == BehaviorType.VERIFY:
            return VerificationRequirement(required=True, reason=VerificationReason.LOW_CONFIDENCE, depth=VerificationDepth.STANDARD)

        ra = context.reasoning_assessment or {}
        confidence = ra.get("confidence", 1.0)
        risk = ra.get("risk", 0.0)

        if confidence < 0.4:
            return VerificationRequirement(required=True, reason=VerificationReason.LOW_CONFIDENCE, depth=VerificationDepth.STANDARD)
        if risk > 0.7:
            return VerificationRequirement(required=True, reason=VerificationReason.HIGH_RISK, depth=VerificationDepth.DEEP)
        if context.policy_constraints.get("contradicting_evidence", False):
            return VerificationRequirement(required=True, reason=VerificationReason.CONFLICTING_EVIDENCE, depth=VerificationDepth.STANDARD)
        return VerificationRequirement(required=False)

from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorEligibilityGate:
    """Hard semantic eligibility gate. Denials are never utility penalties."""

    def filter(
        self,
        candidates: list[BehaviorCandidate],
        context: BehaviorSelectionContext,
    ) -> list[BehaviorCandidate]:
        return [candidate for candidate in candidates if self._is_eligible(candidate, context)]

    def _is_eligible(
        self,
        candidate: BehaviorCandidate,
        context: BehaviorSelectionContext,
    ) -> bool:
        if BehaviorConstraint.POLICY_BLOCKED in candidate.constraints:
            return False

        policy = context.policy
        if policy is not None:
            if policy.tenant_id != context.tenant_id:
                return False
            if candidate.behavior_type.value in policy.blocked_behaviors:
                return False

        if BehaviorConstraint.TENANT_RESTRICTED in candidate.constraints:
            if policy is None:
                return False
            if candidate.behavior_type.value not in policy.allowed_behaviors:
                return False

        if candidate.behavior_type == BehaviorType.REFUSE:
            # Refusal remains available by default. A policy may explicitly block it
            # through blocked_behaviors, but callers cannot disable it via a loose flag.
            return True

        return True

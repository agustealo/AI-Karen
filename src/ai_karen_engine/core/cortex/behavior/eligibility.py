from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorEligibilityGate:
    """Hard semantic eligibility gate executed before CORTEX scoring."""

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
        if candidate.behavior_type.value in context.policy_constraints.blocked_behaviors:
            return False
        if BehaviorConstraint.TENANT_RESTRICTED in candidate.constraints:
            return False
        if BehaviorConstraint.CAPABILITY_UNAVAILABLE in candidate.constraints:
            return False
        if (
            candidate.behavior_type == BehaviorType.REFUSE
            and not context.policy_constraints.allow_refuse
        ):
            return False
        return True

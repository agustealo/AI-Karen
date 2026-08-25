from __future__ import annotations

from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorCandidate,
    BehaviorConstraint,
    BehaviorSelectionContext,
    BehaviorType,
)


class BehaviorEligibilityGate:
    """Determines which behaviors are semantically eligible."""

    def filter(self, candidates: list[BehaviorCandidate], context: BehaviorSelectionContext) -> list[BehaviorCandidate]:
        eligible = []
        for c in candidates:
            if self._is_eligible(c, context):
                eligible.append(c)
        return eligible

    def _is_eligible(self, candidate: BehaviorCandidate, context: BehaviorSelectionContext) -> bool:
        if BehaviorConstraint.POLICY_BLOCKED in candidate.constraints:
            return False
        if BehaviorConstraint.TENANT_RESTRICTED in candidate.constraints and context.tenant_id:
            return True
        return not (candidate.behavior_type == BehaviorType.REFUSE and context.policy_constraints.get("allow_refuse", True) is False)

"""Approval attestation for personal planner effects.

The runtime, not the model or action arguments, creates this object after
checking a concrete authenticated principal and action. It binds the approval
to one action fingerprint so approval cannot be transferred across mutations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from ai_karen_engine.core.planner.action_contract import AuthorizedPlannerAction


def action_fingerprint(action: AuthorizedPlannerAction) -> str:
    return hashlib.sha256(action.model_dump_json(exclude={"explicit_user_authorization"}).encode()).hexdigest()


@dataclass(frozen=True)
class PlannerRuntimeApproval:
    tenant_id: UUID
    owner_id: UUID
    action_fingerprint: str
    correlation_id: str

    def matches(self, *, tenant_id: UUID, owner_id: UUID, action: AuthorizedPlannerAction) -> bool:
        return (
            self.tenant_id == tenant_id
            and self.owner_id == owner_id
            and self.correlation_id == action.correlation_id
            and self.action_fingerprint == action_fingerprint(action)
        )

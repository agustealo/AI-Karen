"""Governed planner action adapter for the canonical ChatRuntime execution path.

Caller must independently verify policy approval and authenticated identity.
This adapter is not an intent classifier, tool registry or route.
"""

from __future__ import annotations

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.planner.action_contract import AuthorizedPlannerAction, PlannerAction
from ai_karen_engine.core.planner.contracts import CommitmentMutation, PersonalCommitment, PersistedCommitmentReceipt
from ai_karen_engine.services.personal_planner import PersonalPlannerService, PlannerAuthorizationError


async def execute_authorized_planner_action(
    action: AuthorizedPlannerAction,
    *,
    authenticated_user: UserData,
    runtime_policy_approved: bool,
    service: PersonalPlannerService | None = None,
) -> tuple[PersonalCommitment, PersistedCommitmentReceipt]:
    """Run only after ChatRuntime policy explicitly permits this mutation."""
    if runtime_policy_approved is not True:
        raise PlannerAuthorizationError("Runtime policy denied planner mutation")
    owner = service if service is not None else PersonalPlannerService()
    if action.action is PlannerAction.CREATE:
        assert action.title is not None and action.timezone is not None
        return await owner.create(
            user=authenticated_user, title=action.title,
            timezone=action.timezone, idempotency_key=action.idempotency_key,
            correlation_id=action.correlation_id,
        )
    assert action.commitment_id is not None and action.expected_revision is not None
    assert action.title is not None
    return await owner.update(
        user=authenticated_user, commitment_id=action.commitment_id,
        mutation=CommitmentMutation(
            idempotency_key=action.idempotency_key,
            expected_revision=action.expected_revision,
            title=action.title,
        ),
        correlation_id=action.correlation_id,
    )

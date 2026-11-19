"""Governed planner action adapter for the canonical ChatRuntime execution path.

Caller must independently verify policy approval and authenticated identity.
This adapter is not an intent classifier, tool registry or route.
"""

from __future__ import annotations

import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.planner.action_contract import AuthorizedPlannerAction, PlannerAction
from ai_karen_engine.core.planner.contracts import CommitmentMutation, PersonalCommitment, PersistedCommitmentReceipt
from ai_karen_engine.services.personal_planner import PersonalPlannerService, PlannerAuthorizationError, PlannerPrincipal
from ai_karen_engine.core.runtime.planner_approval import PlannerRuntimeApproval


async def execute_authorized_planner_action(
    action: AuthorizedPlannerAction,
    *,
    authenticated_user: UserData,
    runtime_approval: PlannerRuntimeApproval | None,
    service: PersonalPlannerService | None = None,
) -> tuple[PersonalCommitment, PersistedCommitmentReceipt]:
    """Run only after ChatRuntime policy explicitly permits this mutation."""
    if runtime_approval is None:
        raise PlannerAuthorizationError("Runtime approval required for planner mutation")
    principal = PlannerPrincipal.from_authenticated_user(authenticated_user)
    if not runtime_approval.matches(tenant_id=principal.tenant_id, owner_id=principal.owner_id, action=action):
        raise PlannerAuthorizationError("Runtime approval does not match principal and action")
    owner = service if service is not None else PersonalPlannerService()
    if action.action is PlannerAction.CREATE:
        assert action.title is not None and action.timezone is not None
        return await owner.create(
            user=authenticated_user, title=action.title,
            timezone=action.timezone, idempotency_key=action.idempotency_key,
            correlation_id=action.correlation_id,
        )
    assert action.commitment_id is not None and action.expected_revision is not None
    return await owner.update(
        user=authenticated_user, commitment_id=action.commitment_id,
        mutation=CommitmentMutation(
            idempotency_key=action.idempotency_key,
            expected_revision=action.expected_revision,
            title=action.title,
            status=action.status,
        ),
        correlation_id=action.correlation_id,
    )


def parse_personal_planner_create(query: str) -> tuple[str, str] | None:
    """Parse one explicit unscheduled personal task, never infer a due date.

    This parser only extracts task arguments for ChatRuntime. It does not
    authorize the intent, resolve a profile, or perform any persistence.
    Time-bound requests require a separate, due-date-aware contract.
    """
    if not isinstance(query, str) or len(query) > 1024:
        return None
    normalized = " ".join(query.strip().split())
    match = re.fullmatch(
        r"(?:please\s+)?(?:create|add|make)\s+(?:me\s+)?(?:a\s+)?"
        r"(?:personal\s+)?(?:task|commitment)\s+(?:to|for)\s+"
        r"(?P<title>.+?)\s+(?:in\s+|timezone\s+)"
        r"(?P<timezone>UTC|[A-Za-z_][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)+)[.!]?",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    title = match.group("title").strip()
    timezone = match.group("timezone")
    if not (1 <= len(title) <= 240 and 1 <= len(timezone) <= 128):
        return None
    # No due_at, recurrence or notification contract is attached to this
    # action. Decline explicit scheduling language rather than committing a
    # task whose displayed title implies an appointment/reminder was created.
    if re.search(
        r"\b(?:today|tomorrow|tonight|yesterday|this\s+(?:morning|afternoon|evening|"
        r"week|weekend|month)|next\s+\w+|on\s+(?:monday|tuesday|wednesday|"
        r"thursday|friday|saturday|sunday)|every\s+(?:day|week|month|"
        r"year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"daily|weekly|monthly|yearly|recurring|remind\s+me)\b"
        r"|\b(?:by|before|after|until|on|at)\s+(?:"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"tomorrow|tonight|noon|midnight|end\s+of\s+(?:day|week|month))\b"
        r"|\b(?:in|within)\s+\d+\s+"
        r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b"
        r"|\b(?:at|by|before|after|until|on)\s+\d{1,4}(?::\d{2})?"
        r"(?:[/-]\d{1,2}(?:[/-]\d{1,4})?)?\s*(?:am|pm)?\b"
        r"|\b\d{4}-\d{2}-\d{2}\b",
        title,
        re.IGNORECASE,
    ):
        return None
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return title, timezone


def parse_personal_planner_completion(query: str) -> tuple[UUID, int] | None:
    """Accept only a fully specified task UUID and optimistic-lock revision.

    A task name or conversational pronoun is not an authorized task reference.
    ChatRuntime uses the returned values only after a scoped policy decision.
    """
    if not isinstance(query, str) or len(query) > 512:
        return None
    match = re.fullmatch(
        r"(?:please\s+)?(?:complete|finish|mark\s+as\s+completed|"
        r"mark\s+completed|mark)\s+"
        r"(?:my\s+)?(?:personal\s+)?(?:task|commitment)\s+"
        r"(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s+"
        r"(?:at\s+)?revision\s+(?P<revision>[1-9][0-9]{0,8})"
        r"(?:\s+as\s+(?:completed|done))?[.!]?",
        " ".join(query.strip().split()),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        task_id = UUID(match.group("id"))
        if task_id.int == 0:
            return None
        return task_id, int(match.group("revision"))
    except ValueError:
        return None

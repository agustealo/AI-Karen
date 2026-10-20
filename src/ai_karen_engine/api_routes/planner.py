"""Read-only personal planner HTTP ingress.

Registration is intentionally gated until runtime authorization and a
product feature flag are wired. Never accepts tenant/owner identity from the
request payload, and does not execute automation tasks.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.planner.contracts import PersonalCommitment
from ai_karen_engine.persistence.repositories.personal_planner_repository import PlannerNotFoundError
from ai_karen_engine.services.personal_planner import PersonalPlannerService, PlannerAuthorizationError

router = APIRouter(prefix="/api/planner", tags=["personal-planner"])


@router.get("/commitments/{commitment_id}", response_model=PersonalCommitment)
async def get_personal_commitment(
    commitment_id: UUID,
    user: UserData = Depends(get_current_user),
) -> PersonalCommitment:
    """Fetch a commitment scoped exclusively to verified session identity."""
    try:
        return await PersonalPlannerService().get(user=user, commitment_id=commitment_id)
    except PlannerAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Verified tenant and user required") from exc
    except PlannerNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Commitment not found") from exc

"""Feature-gated personal planner HTTP ingress.

Registration is intentionally gated until runtime authorization and a
product feature flag are wired. Never accepts tenant/owner identity from the
request payload, and does not execute automation tasks.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.planner.contracts import PersonalCommitment, CommitmentMutation, PersistedCommitmentReceipt
from ai_karen_engine.persistence.repositories.personal_planner_repository import PlannerNotFoundError, PlannerConflictError
from ai_karen_engine.services.personal_planner import PersonalPlannerService, PlannerAuthorizationError
from ai_karen_engine.middleware.correlation_middleware import get_request_correlation_id
from ai_karen_engine.core.runtime.presentation_contract import validate_presentation

router = APIRouter(prefix="/api/planner", tags=["personal-planner"])
write_router = APIRouter(prefix="/api/planner", tags=["personal-planner"])


@router.get("/commitments", response_model=list[PersonalCommitment])
async def list_personal_commitments(
    limit: int = Query(default=20, ge=1, le=20),
    user: UserData = Depends(get_current_user),
) -> list[PersonalCommitment]:
    """Read only commitments belonging to the authenticated planner principal."""
    try:
        return await PersonalPlannerService().list_owned(user=user, limit=limit)
    except PlannerAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Planner permission denied") from exc


@router.get("/commitments/presentation")
async def list_personal_commitment_presentation(
    request: Request,
    limit: int = Query(default=20, ge=1, le=20),
    user: UserData = Depends(get_current_user),
) -> dict:
    """Present authorized planner reads only; never execute planner changes."""
    try:
        commitments = await PersonalPlannerService().list_owned(user=user, limit=limit)
    except PlannerAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Planner permission denied") from exc
    if not commitments:
        return {"presentation": None, "empty": True}
    correlation_id = get_request_correlation_id(request)
    correlation_id = str(correlation_id or uuid4())[:128]
    candidate = {
        "schema_version": 1,
        "presentation_id": f"planner-{correlation_id}",
        "component_type": "planner.task_list",
        "evidence_ref": f"planner-owned-read:{correlation_id}",
        "correlation_id": correlation_id,
        "data": {"tasks": [
            {"id": str(item.id), "title": item.title, "status": item.status.value}
            for item in commitments
        ]},
    }
    presentation = validate_presentation(candidate)
    if presentation is None:
        raise HTTPException(status_code=500, detail="Planner presentation unavailable")
    return {"presentation": presentation, "empty": False}


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


class PlannerCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    timezone: str = Field(min_length=1, max_length=128)
    idempotency_key: UUID


class PlannerMutationResponse(BaseModel):
    commitment: PersonalCommitment
    receipt: PersistedCommitmentReceipt


def _planner_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlannerAuthorizationError):
        return HTTPException(status_code=403, detail="Planner permission denied")
    if isinstance(exc, PlannerNotFoundError):
        return HTTPException(status_code=404, detail="Commitment not found")
    if isinstance(exc, PlannerConflictError):
        return HTTPException(status_code=409, detail="Planner revision or idempotency conflict")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail="Invalid planner mutation")
    raise exc


@write_router.post("/commitments", response_model=PlannerMutationResponse)
async def create_personal_commitment(
    payload: PlannerCreateRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PlannerMutationResponse:
    correlation_id = get_request_correlation_id(request)
    try:
        commitment, receipt = await PersonalPlannerService().create(
            user=user, title=payload.title, timezone=payload.timezone,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
        )
        return PlannerMutationResponse(commitment=commitment, receipt=receipt)
    except (PlannerAuthorizationError, PlannerConflictError, ValueError) as exc:
        raise _planner_http_error(exc) from exc


@write_router.patch("/commitments/{commitment_id}", response_model=PlannerMutationResponse)
async def update_personal_commitment(
    commitment_id: UUID,
    payload: CommitmentMutation,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> PlannerMutationResponse:
    correlation_id = get_request_correlation_id(request)
    try:
        commitment, receipt = await PersonalPlannerService().update(
            user=user, commitment_id=commitment_id,
            mutation=payload, correlation_id=correlation_id,
        )
        return PlannerMutationResponse(commitment=commitment, receipt=receipt)
    except (PlannerAuthorizationError, PlannerConflictError, PlannerNotFoundError, ValueError) as exc:
        raise _planner_http_error(exc) from exc

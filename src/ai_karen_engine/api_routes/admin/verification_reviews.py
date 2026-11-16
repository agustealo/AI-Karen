"""Thin authenticated ingress for independent verification-review labels.

No review request may contain behavior/candidate propensities, policy versions,
feature snapshots or prompt text. The Intelligence owner resolves those from
the canonical tenant-scoped runtime learning lineage.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    get_rbac_manager,
    require_permission,
)
from ai_karen_engine.core.intelligence.ml.verification_review_workflow import (
    ReviewJudgement,
    VerificationReviewWorkflow,
)
from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError
from ai_karen_engine.core.runtime.trajectory.store import TrajectoryStoreError
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/verification/reviews", tags=["verification-reviews"])


class VerificationReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    decision_observation_id: str = Field(
        min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    subject_user_id: UUID
    reward: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    verification_needed: StrictBool


class VerificationReviewResponse(BaseModel):
    stored: bool
    receipt_count: int
    evidence_schema: str
    decision_observation_id: str
    evaluation_mode: str
    policy_activated: bool
    decision_provenance: str


def get_verification_review_workflow() -> VerificationReviewWorkflow:
    return VerificationReviewWorkflow()


@router.post("/", response_model=VerificationReviewResponse, status_code=201)
async def submit_verification_review(
    body: VerificationReviewRequest,
    request: Request,
    current_user: UserData = Depends(
        require_permission(Permission.VERIFICATION_REVIEW)
    ),
    workflow: VerificationReviewWorkflow = Depends(
        get_verification_review_workflow
    ),
) -> VerificationReviewResponse:
    """Issue a review only after live session/RBAC and stored lineage validation."""
    if auth_config.should_bypass_auth():
        # Development identities are never acceptable independent reviewers.
        raise HTTPException(
            status_code=403,
            detail="Independent review requires production session authentication",
        )
    if (
        not current_user.user_id
        or not current_user.tenant_id
        or current_user.tenant_id == "default"
        or not current_user.is_active
        or not current_user.is_verified
    ):
        raise HTTPException(status_code=403, detail="Active verified identity required")

    # Only the canonical RBAC catalog resolves role and authenticated grants.
    # Never accept permission strings from this request body.
    effective_permissions = get_rbac_manager().get_user_permissions(current_user)
    principal = AuthenticatedPrincipal(
        user_id=str(current_user.user_id),
        tenant_id=str(current_user.tenant_id),
        roles=list(current_user.roles or []),
        permissions=sorted(item.value for item in effective_permissions),
    )
    correlation_id: Any = getattr(request.state, "correlation_id", None)
    if not isinstance(correlation_id, str):
        correlation_id = None

    try:
        result = await workflow.submit(
            ReviewJudgement(
                decision_observation_id=body.decision_observation_id,
                subject_user_id=str(body.subject_user_id),
                reward=body.reward,
                verification_needed=body.verification_needed,
            ),
            reviewer=principal,
            correlation_id=correlation_id,
        )
        return VerificationReviewResponse(**result)
    except PermissionError as exc:
        logger.warning(
            "verification_review.forbidden",
            extra={"tenant_id": principal.tenant_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=403, detail="Review access denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Recorded decision unavailable") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except (TrajectoryStoreError, OutcomeStoreError) as exc:
        logger.exception(
            "verification_review.persistence_failed",
            extra={"tenant_id": principal.tenant_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail="Governed decision or review evidence unavailable",
        ) from exc


__all__ = ["router", "submit_verification_review", "get_verification_review_workflow"]

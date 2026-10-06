"""Thin HTTP ingress for Runtime-owned human approvals."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.approvals import (
    ApprovalNotFoundError,
    ApprovalScopeError,
    ApprovalStateError,
    get_approval_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    reason: Optional[str] = Field(default=None, max_length=1000)


class ApprovalResponse(BaseModel):
    approval_id: str
    conversation_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    intent: str
    risk_level: str
    reason_codes: List[str] = Field(default_factory=list)
    status: str
    decision_reason: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    decided_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None


def _response(record: dict) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=record["approval_id"],
        conversation_id=record.get("conversation_id"),
        policy_decision_id=record.get("policy_decision_id"),
        intent=record["intent"],
        risk_level=record["risk_level"],
        reason_codes=list(record.get("reason_codes") or []),
        status=record["status"],
        decision_reason=record.get("decision_reason"),
        created_at=record["created_at"],
        expires_at=record["expires_at"],
        decided_at=record.get("decided_at"),
        consumed_at=record.get("consumed_at"),
    )


@router.get("/", response_model=List[ApprovalResponse])
async def list_approvals(
    conversation_id: Optional[UUID] = None,
    user: UserData = Depends(get_current_user),
):
    """List actionable Runtime approvals within the caller's authenticated scope."""
    try:
        records = await get_approval_service().list_actionable(
            user=user,
            conversation_id=str(conversation_id) if conversation_id else None,
        )
        return [_response(record) for record in records]
    except ApprovalScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "approvals.list.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(status_code=500, detail="Failed to list approvals") from exc


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: UserData = Depends(get_current_user),
):
    """Read one approval within the authenticated tenant/user scope."""
    try:
        record = await get_approval_service().get(approval_id, user=user)
        return _response(record)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ApprovalScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    user: UserData = Depends(get_current_user),
):
    """Persist a one-time human decision.

    This endpoint never executes the action. The original request must be
    resubmitted with the approval receipt, where ChatRuntime re-evaluates
    policy and atomically consumes the approved receipt before execution.
    """
    try:
        record = await get_approval_service().decide(
            approval_id,
            user=user,
            decision=request.decision,
            reason=request.reason,
        )
        return _response(record)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ApprovalScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "approvals.decision.failed",
            extra={
                "approval_id": approval_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to decide approval") from exc

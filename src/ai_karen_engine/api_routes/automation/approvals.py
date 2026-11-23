"""Thin HTTP ingress for Runtime-owned human approvals."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool

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


class DocumentAuthorDraftProfile(BaseModel):
    profile_id: UUID
    label: str
    kind: str


@router.get("/document-consent/profiles", response_model=List[DocumentAuthorDraftProfile])
async def list_document_author_draft_profiles(request: Request):
    """Return only canonical author-owned draft metadata after bearer checks."""
    try:
        return await get_approval_service().list_document_author_draft_profiles(
            request=request,
        )
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Draft profiles unavailable") from exc


class DocumentAuthorInitiation(BaseModel):
    """Source selector only; no client-side identity, digest or expiry authority."""

    model_config = {"extra": "forbid"}

    profile_id: UUID
    artifact_id: UUID
    style_use_allowed: StrictBool


@router.post("/document-consent/initiate", response_model=ApprovalResponse)
async def initiate_document_author_consent(
    request: Request,
    body: DocumentAuthorInitiation,
):
    """Request source-scoped review; never issue a receipt or ingest content."""
    from uuid import uuid4

    try:
        record = await get_approval_service().initiate_document_consent(
            request=request,
            profile_id=str(body.profile_id),
            artifact_id=str(body.artifact_id),
            style_use_allowed=body.style_use_allowed,
            correlation_id=str(uuid4()),
        )
        return _response(record)
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(
            status_code=403, detail="Document initiation denied",
        ) from exc


class DocumentAuthorConfirmation(BaseModel):
    """Explicit first-party author gesture, not a chat or tool approval."""

    confirmed: StrictBool


class DocumentAuthorConsentPreview(BaseModel):
    approval_id: str
    status: str
    profile_id: str
    artifact_id: str
    source_name: str
    source_bytes: int
    source_mime_type: str
    source_sha256: str
    analysis_allowed: bool
    style_use_allowed: bool
    expires_at: datetime
    approval_expires_at: datetime


@router.get(
    "/document-consent/{approval_id}",
    response_model=DocumentAuthorConsentPreview,
)
async def get_document_author_confirmation(
    approval_id: UUID,
    request: Request,
):
    """Read only ledger-bound metadata after revalidating the author's bearer."""
    try:
        record, scope, source = await get_approval_service().get_document_consent_review(
            str(approval_id), request=request,
        )
        return DocumentAuthorConsentPreview(
            approval_id=str(approval_id),
            status=record["status"],
            profile_id=scope.profile_id,
            artifact_id=scope.artifact_id,
            source_name=str(source["name"]),
            source_bytes=int(source["bytes"]),
            source_mime_type=str(source["mime_type"]),
            source_sha256=scope.source_sha256,
            analysis_allowed=scope.analysis_allowed,
            style_use_allowed=scope.style_use_allowed,
            expires_at=scope.expires_at,
            approval_expires_at=record["expires_at"],
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Document approval unavailable") from exc


@router.post(
    "/document-consent/{approval_id}/confirm",
    response_model=ApprovalResponse,
)
async def confirm_document_author_consent(
    approval_id: UUID,
    request: Request,
    body: DocumentAuthorConfirmation,
):
    """Confirm only a durable source scope from a freshly checked author bearer.

    Deliberate confirmation does not mint the document-consent receipt.
    Final issuance still requires the existing one-shot SQL CAS and the
    canonical source row lock. Never accept model/chat approval metadata.
    """
    try:
        record = await get_approval_service().confirm_stored_document_consent(
            str(approval_id), request=request, confirmed=body.confirmed,
        )
        return _response(record)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Document confirmation denied") from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail="Document confirmation conflict") from exc


class DocumentAuthorConsentReceipt(BaseModel):
    approval_id: str
    receipt_id: UUID
    status: str


@router.get(
    "/document-consent/{approval_id}/receipt",
    response_model=DocumentAuthorConsentReceipt,
)
async def recover_document_author_consent_receipt(
    approval_id: UUID,
    request: Request,
):
    """Recover a previously issued receipt using current PostgreSQL evidence."""
    try:
        receipt = await get_approval_service().recover_stored_document_consent_receipt(
            str(approval_id), request=request,
        )
        if receipt is None:
            raise HTTPException(
                status_code=404,
                detail="Current document consent receipt not found",
            )
        return DocumentAuthorConsentReceipt(
            approval_id=str(approval_id),
            receipt_id=UUID(receipt),
            status="issued",
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Document receipt unavailable") from exc


@router.post(
    "/document-consent/{approval_id}/issue",
    response_model=DocumentAuthorConsentReceipt,
)
async def issue_document_author_consent(
    approval_id: UUID,
    request: Request,
):
    """Mint the actual receipt only through the durable approved SQL contract."""
    from uuid import uuid4

    try:
        receipt = await get_approval_service().issue_stored_document_consent(
            str(approval_id),
            request=request,
            correlation_id=str(uuid4()),
        )
        return DocumentAuthorConsentReceipt(
            approval_id=str(approval_id),
            receipt_id=UUID(receipt),
            status="issued",
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Document issuance denied") from exc
    except (ApprovalStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Document receipt not issued") from exc


class DocumentAuthorRevocationPreview(BaseModel):
    """Stored provenance only; does not claim the receipt is still current."""
    approval_id: UUID
    status: str
    profile_id: UUID
    artifact_id: UUID
    source_sha256: str


@router.get(
    "/document-consent/{approval_id}/revoke-review",
    response_model=DocumentAuthorRevocationPreview,
)
async def review_document_author_revocation(
    approval_id: UUID,
    request: Request,
):
    """Present immutable consumed-approval scope without original token/file."""
    try:
        record, scope = await get_approval_service().get_document_consent_revocation_scope(
            str(approval_id), request=request,
        )
        return DocumentAuthorRevocationPreview(
            approval_id=approval_id,
            status=record["status"],
            profile_id=UUID(scope.profile_id),
            artifact_id=UUID(scope.artifact_id),
            source_sha256=scope.source_sha256,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Revocation review denied") from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail="No issued author consent") from exc


class DocumentAuthorRevocation(BaseModel):
    """Deliberate human revocation; no caller-controlled receipt scope."""

    model_config = {"extra": "forbid"}
    confirmed: StrictBool


class DocumentAuthorRevocationResponse(BaseModel):
    approval_id: UUID
    status: str


@router.post(
    "/document-consent/{approval_id}/revoke",
    response_model=DocumentAuthorRevocationResponse,
)
async def revoke_document_author_consent(
    approval_id: UUID,
    request: Request,
    body: DocumentAuthorRevocation,
):
    """Revoke an issued author receipt through runtime policy and SQL owner."""
    from uuid import uuid4

    if body.confirmed is not True:
        raise HTTPException(status_code=403, detail="Explicit revocation required")
    try:
        await get_approval_service().revoke_stored_document_consent(
            str(approval_id), request=request, confirmed=body.confirmed,
            correlation_id=str(uuid4()),
        )
        return DocumentAuthorRevocationResponse(
            approval_id=approval_id, status="revoked",
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document approval not found") from exc
    except (ApprovalScopeError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Author revocation denied") from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail="Author revocation not recorded") from exc


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
        raise HTTPException(status_code=403, detail="Approval access denied") from exc
    except Exception as exc:
        logger.error(
            "approvals.list.failed",
            extra={
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "error_type": type(exc).__name__,
            },
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
        raise HTTPException(status_code=403, detail="Approval access denied") from exc


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
        raise HTTPException(status_code=403, detail="Approval access denied") from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail="Approval state conflict") from exc
    except Exception as exc:
        logger.error(
            "approvals.decision.failed",
            extra={
                "approval_id": approval_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(status_code=500, detail="Failed to decide approval") from exc

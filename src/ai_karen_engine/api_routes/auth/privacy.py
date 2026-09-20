"""Authenticated self-service privacy API.

Routes derive user and tenant identity exclusively from the canonical auth
principal. The durable privacy service owns request state and processing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ai_karen_engine.api_routes.shared.schemas import SuccessResponse
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.privacy_compliance import (
    DataExportFormat,
    ErasureType,
    PrivacyComplianceService,
    PrivacyRequestStatus,
    get_privacy_compliance_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["privacy"], prefix="/privacy")


class DataExportRequest(BaseModel):
    """Self-service export options. Identity comes from authentication."""

    data_types: List[str] = Field(
        default_factory=lambda: ["all"],
        description="Supported: memories, conversations, analytics, audit_logs, all",
    )
    export_format: DataExportFormat = Field(default=DataExportFormat.JSON)
    include_pii: bool = Field(
        default=False,
        description="Include the authenticated user's raw PII in the returned export",
    )


class DataErasureRequest(BaseModel):
    """Self-service erasure options. Unsupported modes fail closed."""

    erasure_type: ErasureType = Field(default=ErasureType.HARD_DELETE)
    data_types: List[str] = Field(
        default_factory=lambda: ["all"],
        description="Supported: memories, conversations, all",
    )


class PrivacyProcessRequest(BaseModel):
    verification_token: str = Field(..., min_length=16)
    include_pii: bool = Field(default=False)


class ContentSanitizeRequest(BaseModel):
    """Sensitive content accepted in the request body, never as URL parameters."""

    content: str = Field(..., min_length=1)
    max_length: int = Field(default=100, ge=1)


class PrivacyRequestResponse(BaseModel):
    request_id: str
    status: PrivacyRequestStatus
    verification_token: str
    next_steps: str


class PrivacyRequestStatusResponse(BaseModel):
    request_id: str
    status: PrivacyRequestStatus
    request_type: str
    data_types: List[str]
    created_at: str
    completed_at: Optional[str] = None
    result_metadata: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id") or str(uuid.uuid4())


def get_privacy_service() -> PrivacyComplianceService:
    return get_privacy_compliance_service()


def _identity(user: UserData) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.tenant_id or "").strip()
    if not user_id or not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Durable user and tenant identity are required for privacy operations",
        )
    return user_id, tenant_id


def _translate_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Privacy request not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    logger.exception("privacy.request.failed")
    return HTTPException(status_code=500, detail="Privacy operation failed")


@router.post("/export/request", response_model=PrivacyRequestResponse)
async def request_data_export(
    request_data: DataExportRequest,
    http_request: Request,
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> PrivacyRequestResponse:
    """Create a durable export request for the authenticated user only."""

    user_id, tenant_id = _identity(current_user)
    correlation_id = get_correlation_id(http_request)
    try:
        privacy_request = await privacy_service.create_privacy_request(
            request_type="export",
            user_id=user_id,
            tenant_id=tenant_id,
            data_types=request_data.data_types,
            export_format=request_data.export_format,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        raise _translate_service_error(exc) from exc

    return PrivacyRequestResponse(
        request_id=privacy_request.request_id,
        status=privacy_request.status,
        verification_token=str(privacy_request.verification_token or ""),
        next_steps=(
            "Submit the one-time verification token to this request's process endpoint. "
            "The raw token is returned only at creation and is not stored."
        ),
    )


@router.post("/erasure/request", response_model=PrivacyRequestResponse)
async def request_data_erasure(
    request_data: DataErasureRequest,
    http_request: Request,
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> PrivacyRequestResponse:
    """Create a durable destructive-data request for the authenticated user only."""

    user_id, tenant_id = _identity(current_user)
    correlation_id = get_correlation_id(http_request)
    try:
        privacy_request = await privacy_service.create_privacy_request(
            request_type="erasure",
            user_id=user_id,
            tenant_id=tenant_id,
            data_types=request_data.data_types,
            erasure_type=request_data.erasure_type,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        raise _translate_service_error(exc) from exc

    return PrivacyRequestResponse(
        request_id=privacy_request.request_id,
        status=privacy_request.status,
        verification_token=str(privacy_request.verification_token or ""),
        next_steps=(
            "Permanent deletion is not executed until the one-time verification token "
            "is submitted to the process endpoint."
        ),
    )


@router.get("/request/{request_id}/status", response_model=PrivacyRequestStatusResponse)
async def get_privacy_request_status(
    request_id: uuid.UUID,
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> PrivacyRequestStatusResponse:
    """Read one of the authenticated user's durable privacy requests."""

    user_id, tenant_id = _identity(current_user)
    try:
        privacy_request = await privacy_service.get_privacy_request_status(
            str(request_id),
            user_id=user_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        raise _translate_service_error(exc) from exc
    if privacy_request is None:
        raise HTTPException(status_code=404, detail="Privacy request not found")

    return PrivacyRequestStatusResponse(
        request_id=privacy_request.request_id,
        status=privacy_request.status,
        request_type=privacy_request.request_type,
        data_types=list(privacy_request.data_types or []),
        created_at=privacy_request.created_at.isoformat(),
        completed_at=(
            privacy_request.completed_at.isoformat()
            if privacy_request.completed_at
            else None
        ),
        result_metadata=dict(privacy_request.result_metadata or {}),
        error_message=privacy_request.error_message,
    )


@router.post("/request/{request_id}/process")
async def process_privacy_request(
    request_id: uuid.UUID,
    request_data: PrivacyProcessRequest,
    http_request: Request,
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> SuccessResponse:
    """Confirm and synchronously execute a pending self-service privacy request."""

    user_id, tenant_id = _identity(current_user)
    correlation_id = get_correlation_id(http_request)
    try:
        result = await privacy_service.process_privacy_request(
            str(request_id),
            verification_token=request_data.verification_token,
            user_id=user_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            include_pii=request_data.include_pii,
        )
    except Exception as exc:
        raise _translate_service_error(exc) from exc

    return SuccessResponse(
        data=result,
        message="Privacy request completed successfully",
        correlation_id=correlation_id,
        timestamp=datetime.utcnow(),
    )


@router.post("/content/sanitize")
async def sanitize_content(
    request_data: ContentSanitizeRequest,
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> Dict[str, Any]:
    """Create a safe preview without placing sensitive content in the request URL."""

    _identity(current_user)
    return privacy_service.create_safe_content_preview(
        request_data.content,
        max_length=request_data.max_length,
    )


@router.get("/health")
async def privacy_health_check(
    current_user: UserData = Depends(get_current_user),
    privacy_service: PrivacyComplianceService = Depends(get_privacy_service),
) -> Dict[str, Any]:
    """Report only privacy capabilities backed by active implementations."""

    _identity(current_user)
    payload = await privacy_service.health()
    payload["service"] = "privacy_compliance"
    payload["timestamp"] = datetime.utcnow().isoformat()
    return payload


__all__ = ["router"]

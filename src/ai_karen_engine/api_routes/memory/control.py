"""
Memory Control API Routes.

Thin ingress for operator/user-facing memory controls. RBAC and request
translation stay here; persistence and governance execute through the canonical
MemoryControlService composed by Runtime.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ai_karen_engine.api_routes.shared.schemas import ErrorHandler
from ai_karen_engine.auth.rbac_middleware import check_scope
from ai_karen_engine.core.memory.memory_runtime_manager import (
    get_memory_control_service,
    get_memory_manager,
    get_metrics,
)
from ai_karen_engine.core.runtime.resilience import get_feature_flags
from ai_karen_engine.utils.pydantic_base import ISO8601Model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory/control", tags=["memory-control"])


def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id", str(uuid.uuid4()))


def _memory_manager():
    return get_memory_manager()


def _memory_control():
    return get_memory_control_service()


def _feature_flags():
    return get_feature_flags()


class MemoryInspectorRequest(ISO8601Model):
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    limit: int = Field(20, ge=1, le=100)


class MemoryInspectorResponse(ISO8601Model):
    correlation_id: str
    status: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    limit: int
    feature_flags: Dict[str, bool] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    counts: Dict[str, int] = Field(default_factory=dict)
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)
    recent_assertions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_profile_facts: List[Dict[str, Any]] = Field(default_factory=list)
    recent_episodes: List[Dict[str, Any]] = Field(default_factory=list)
    open_contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    consent_scopes: List[Dict[str, Any]] = Field(default_factory=list)
    retention_policies: List[Dict[str, Any]] = Field(default_factory=list)
    projection_status: List[Dict[str, Any]] = Field(default_factory=list)


class ConsentScopeRequest(ISO8601Model):
    tenant_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    scope_name: str = Field(..., min_length=1, max_length=100)
    granted: bool = Field(...)


class ConsentScopeResponse(ISO8601Model):
    correlation_id: str
    status: str
    scope_id: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    scope_name: Optional[str] = None
    is_granted: Optional[bool] = None
    granted_at: Optional[str] = None
    revoked_at: Optional[str] = None


class ConsentScopeListResponse(ISO8601Model):
    correlation_id: str
    status: str
    items: List[Dict[str, Any]] = Field(default_factory=list)


class RetentionPolicyRequest(ISO8601Model):
    tenant_id: Optional[str] = None
    memory_class: str = Field(..., min_length=1, max_length=50)
    ttl_days: Optional[int] = Field(None, ge=1, le=3650)


class RetentionPolicyResponse(ISO8601Model):
    correlation_id: str
    status: str
    policy_id: Optional[str] = None
    tenant_id: Optional[str] = None
    memory_class: Optional[str] = None
    ttl_days: Optional[int] = None
    updated_at: Optional[str] = None


class RetentionPolicyListResponse(ISO8601Model):
    correlation_id: str
    status: str
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ShadowModeRequest(ISO8601Model):
    enabled: bool
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None


class ShadowModeResponse(ISO8601Model):
    correlation_id: str
    status: str
    enabled: bool
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    effective: bool


class ProfileCorrectionRequest(ISO8601Model):
    tenant_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    correction_text: str = Field(..., min_length=1, max_length=16000)
    profile_area: Optional[str] = Field(None, max_length=128)
    source_ref: Optional[str] = Field(None, max_length=255)
    session_id: Optional[str] = Field(None, max_length=255)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class ProfileCorrectionResponse(ISO8601Model):
    correlation_id: str
    status: str
    result: Dict[str, Any] = Field(default_factory=dict)


class ExportPromotedRequest(ISO8601Model):
    limit: int = Field(100, ge=1, le=500)
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None


class ExportPromotedResponse(ISO8601Model):
    correlation_id: str
    status: str
    count: int
    limit: int
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)


async def _authorize(request: Request, scope: str) -> None:
    if not await check_scope(request, scope):
        correlation_id = get_correlation_id(request)
        error_response = ErrorHandler.create_authorization_error_response(
            correlation_id=correlation_id,
            path=str(request.url.path),
            message=f"Insufficient permissions for {scope}",
        )
        raise HTTPException(status_code=403, detail=error_response.model_dump(mode="json"))


def _audit_control(
    *,
    correlation_id: str,
    action: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    logger.info(
        "memory.control.action",
        extra={
            "correlation_id": correlation_id,
            "action": action,
            "tenant_id": tenant_id,
            "user_id": user_id,
        },
    )


@router.get("/inspector", response_model=MemoryInspectorResponse)
async def inspect_memory(
    request: Request,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 20,
):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:read")
    flags = _feature_flags()
    if not flags.is_enabled("memory_inspector_enabled", tenant_id, user_id):
        raise HTTPException(status_code=403, detail="Memory inspector is disabled")
    snapshot = await _memory_control().inspect_memory_state(
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
    )
    snapshot["feature_flags"] = {
        "memory_inspector_enabled": flags.is_enabled(
            "memory_inspector_enabled", tenant_id, user_id
        ),
        "memory_consent_controls_enabled": flags.is_enabled(
            "memory_consent_controls_enabled", tenant_id, user_id
        ),
        "memory_retention_controls_enabled": flags.is_enabled(
            "memory_retention_controls_enabled", tenant_id, user_id
        ),
        "memory_shadow_mode_enabled": flags.is_enabled(
            "memory_shadow_mode_enabled", tenant_id, user_id
        ),
    }
    snapshot["metrics"] = get_metrics().get("memory_runtime", {})
    snapshot["correlation_id"] = correlation_id
    return MemoryInspectorResponse(**snapshot)


@router.get("/consent", response_model=ConsentScopeListResponse)
async def list_consent_scopes(
    request: Request,
    tenant_id: str,
    user_id: Optional[str] = None,
):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:read")
    if not _feature_flags().is_enabled(
        "memory_consent_controls_enabled", tenant_id, user_id
    ):
        raise HTTPException(status_code=403, detail="Memory consent controls are disabled")
    result = await _memory_control().list_consent_scopes(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return ConsentScopeListResponse(
        correlation_id=correlation_id,
        status=result.get("status", "degraded"),
        items=result.get("items", []),
    )


@router.post("/consent", response_model=ConsentScopeResponse)
async def update_consent_scope(request: Request, body: ConsentScopeRequest):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:write")
    if not _feature_flags().is_enabled(
        "memory_consent_controls_enabled", body.tenant_id, body.user_id
    ):
        raise HTTPException(status_code=403, detail="Memory consent controls are disabled")
    result = await _memory_control().set_consent_scope(
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        scope_name=body.scope_name,
        granted=body.granted,
    )
    _audit_control(
        correlation_id=correlation_id,
        action="consent.update",
        tenant_id=body.tenant_id,
        user_id=body.user_id,
    )
    return ConsentScopeResponse(correlation_id=correlation_id, **result)


@router.get("/retention", response_model=RetentionPolicyListResponse)
async def list_retention_policies(request: Request, tenant_id: Optional[str] = None):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:read")
    if not _feature_flags().is_enabled("memory_retention_controls_enabled", tenant_id):
        raise HTTPException(status_code=403, detail="Memory retention controls are disabled")
    result = await _memory_control().list_retention_policies(tenant_id=tenant_id)
    return RetentionPolicyListResponse(
        correlation_id=correlation_id,
        status=result.get("status", "degraded"),
        items=result.get("items", []),
    )


@router.post("/retention", response_model=RetentionPolicyResponse)
async def update_retention_policy(request: Request, body: RetentionPolicyRequest):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:write")
    if not _feature_flags().is_enabled(
        "memory_retention_controls_enabled", body.tenant_id
    ):
        raise HTTPException(status_code=403, detail="Memory retention controls are disabled")
    result = await _memory_control().set_retention_policy(
        tenant_id=body.tenant_id,
        memory_class=body.memory_class,
        ttl_days=body.ttl_days,
    )
    _audit_control(
        correlation_id=correlation_id,
        action="retention.update",
        tenant_id=body.tenant_id,
    )
    return RetentionPolicyResponse(correlation_id=correlation_id, **result)


@router.get("/shadow-mode", response_model=ShadowModeResponse)
async def get_shadow_mode(
    request: Request,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:read")
    effective = _feature_flags().is_enabled(
        "memory_shadow_mode_enabled", tenant_id, user_id
    )
    return ShadowModeResponse(
        correlation_id=correlation_id,
        status="success",
        enabled=effective,
        tenant_id=tenant_id,
        user_id=user_id,
        effective=effective,
    )


@router.post("/shadow-mode", response_model=ShadowModeResponse)
async def set_shadow_mode(request: Request, body: ShadowModeRequest):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:write")
    flags = _feature_flags()
    if body.tenant_id:
        flags.set_tenant_override(
            body.tenant_id, "memory_shadow_mode_enabled", body.enabled
        )
    elif body.user_id:
        flags.set_user_override(body.user_id, "memory_shadow_mode_enabled", body.enabled)
    else:
        flags.set_global("memory_shadow_mode_enabled", body.enabled)
    effective = flags.is_enabled(
        "memory_shadow_mode_enabled", body.tenant_id, body.user_id
    )
    _audit_control(
        correlation_id=correlation_id,
        action="shadow_mode.update",
        tenant_id=body.tenant_id,
        user_id=body.user_id,
    )
    return ShadowModeResponse(
        correlation_id=correlation_id,
        status="success",
        enabled=body.enabled,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        effective=effective,
    )


@router.post("/profile/correction", response_model=ProfileCorrectionResponse)
async def submit_profile_correction(request: Request, body: ProfileCorrectionRequest):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "memory:write")
    if not _feature_flags().is_enabled(
        "memory_profile_corrections_enabled", body.tenant_id, body.user_id
    ):
        return ProfileCorrectionResponse(
            correlation_id=correlation_id,
            status="disabled",
            result={"status": "skipped", "reason": "Memory profile corrections are disabled"},
        )
    source_text = body.correction_text
    if body.profile_area:
        source_text = f"{body.profile_area}: {source_text}"
    result = await _memory_manager().process_interaction(
        text=source_text,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        source_type="profile_correction",
        source_ref=body.source_ref or body.session_id,
        metadata={
            "profile_area": body.profile_area,
            "confidence": body.confidence,
            "session_id": body.session_id,
            "source_ref": body.source_ref,
        },
        correlation_id=correlation_id,
        policy_context={
            "memory_write_authorized": True,
            "allowed_capabilities": ["memory.write"],
        },
    )
    _audit_control(
        correlation_id=correlation_id,
        action="profile_correction.submit",
        tenant_id=body.tenant_id,
        user_id=body.user_id,
    )
    result["profile_area"] = body.profile_area
    result["confidence"] = body.confidence
    return ProfileCorrectionResponse(
        correlation_id=correlation_id,
        status=str(result.get("status", "success")),
        result=result,
    )


@router.post("/export/promoted", response_model=ExportPromotedResponse)
async def export_promoted(request: Request, body: ExportPromotedRequest):
    correlation_id = get_correlation_id(request)
    await _authorize(request, "admin:read")
    result = await _memory_control().export_promoted_artifacts(
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        limit=body.limit,
    )
    return ExportPromotedResponse(
        correlation_id=correlation_id,
        status=result.get("status", "noop"),
        count=int(result.get("count", 0)),
        limit=int(result.get("limit", body.limit)),
        artifacts=result.get("artifacts", []),
    )


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "memory_control",
        "timestamp": datetime.utcnow().isoformat(),
    }


__all__ = ["router"]

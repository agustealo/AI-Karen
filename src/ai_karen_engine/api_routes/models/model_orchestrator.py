"""Thin model-management API routes.

The application-level router registry admin-scopes this router. Runtime model
state, download policy, jobs, discovery, and lifecycle execution are owned by the
canonical ``ModelDownloadControlService`` and its single orchestrator instance.
This module validates HTTP inputs, delegates, translates domain errors, and emits
structured audit evidence for destructive model removal.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ai_karen_engine.audit_logging import get_audit_logger
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    E_COMPAT,
    E_DISK,
    E_INVALID,
    E_LICENSE,
    E_NET,
    E_NOT_FOUND,
    E_PERM,
    E_QUOTA,
    E_SCHEMA,
    E_VERIFY,
    ModelOrchestratorError,
    ModelOrchestratorService,
    RemoveResult,
)
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    get_model_download_control_service,
)
from ai_karen_engine.error_tracking import get_model_orchestrator_error_tracker
from ai_karen_engine.health import get_model_orchestrator_health_checker
from ai_karen_engine.monitoring import get_model_orchestrator_metrics
from ai_karen_engine.utils.dependency_checks import import_pydantic

BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = logging.getLogger("kari.model_orchestrator_api")
router = APIRouter(prefix="/api/models", tags=["model-orchestrator"])


class ModelDownloadRequest(BaseModel):
    """Request payload for the canonical model-download control plane."""

    model_id: str = Field(..., description="Model identifier in owner/repo form")
    revision: Optional[str] = Field(None, description="Model revision or commit hash")
    channel_id: Optional[str] = Field(None, description="Download channel identifier")
    include_patterns: Optional[List[str]] = Field(None, description="File patterns to include")
    exclude_patterns: Optional[List[str]] = Field(None, description="File patterns to exclude")
    pin: bool = Field(False, description="Pin model to protect it from cleanup")
    force_redownload: bool = Field(False, description="Force a new download")
    storage_key: Optional[str] = Field(None, description="Storage namespace override")
    trust_remote_code: bool = Field(False, description="Allow trusted remote code when policy permits")
    accept_license: bool = Field(False, description="Record license acceptance for this download")


class ModelSummaryResponse(BaseModel):
    model_id: str
    last_modified: Optional[datetime]
    likes: Optional[int]
    downloads: Optional[int]
    storage_key: Optional[str]
    tags: List[str]
    total_size: Optional[int] = None
    description: Optional[str] = None


class ModelInfoResponse(BaseModel):
    model_id: str
    owner: str
    repository: str
    storage_key: str
    files: List[Dict[str, Union[str, int]]]
    total_size: int
    last_modified: Optional[datetime]
    downloads: Optional[int]
    likes: Optional[int]
    tags: List[str]
    license: Optional[str]
    description: Optional[str]
    revision: Optional[str] = None


class ModelRemoveResponse(BaseModel):
    model_id: str
    delete_files: bool
    deleted_artifacts: List[str]
    warnings: List[str]
    metadata: Dict[str, Any]
    message: str


class DownloadChannelResponse(BaseModel):
    id: str
    label: str
    group: str
    storage_key: str
    enabled: bool
    description: str
    model_families: List[str] = Field(default_factory=list)
    modalities: List[str] = Field(default_factory=list)
    admin_only: bool = False
    locked_by_master: bool = False
    effective_enabled: bool = False


class DownloadPolicyResponse(BaseModel):
    master_enabled: bool
    core_runtime_enabled: bool
    plugin_channels_enabled: bool
    image_channels_enabled: bool
    audio_channels_enabled: bool
    vision_channels_enabled: bool
    gguf_external_enabled: bool
    trust_remote_code: bool
    block_new_downloads: bool
    pause_active_downloads: bool
    quarantine_failed_models: bool
    require_license_acceptance: bool
    max_concurrent_downloads: int


class DownloadPolicyUpdateRequest(BaseModel):
    master_enabled: Optional[bool] = None
    core_runtime_enabled: Optional[bool] = None
    plugin_channels_enabled: Optional[bool] = None
    image_channels_enabled: Optional[bool] = None
    audio_channels_enabled: Optional[bool] = None
    vision_channels_enabled: Optional[bool] = None
    gguf_external_enabled: Optional[bool] = None
    trust_remote_code: Optional[bool] = None
    block_new_downloads: Optional[bool] = None
    pause_active_downloads: Optional[bool] = None
    quarantine_failed_models: Optional[bool] = None
    require_license_acceptance: Optional[bool] = None
    max_concurrent_downloads: Optional[int] = Field(default=None, ge=1, le=8)


class DownloadValidationRequest(BaseModel):
    model_id: str
    revision: Optional[str] = None
    channel_id: Optional[str] = None
    trust_remote_code: bool = False
    accept_license: bool = False
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None


class DownloadValidationResponse(BaseModel):
    allowed: bool
    channel_id: str
    model_id: str
    revision: Optional[str] = None
    storage_key: Optional[str] = None
    install_path: Optional[str] = None
    detected_runtime: Optional[str] = None
    detected_modality: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    license_required: bool = False
    trust_remote_code_allowed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DownloadJobResponse(BaseModel):
    job_id: str
    model_id: str
    revision: Optional[str] = None
    channel_id: str
    storage_key: Optional[str] = None
    status: str
    progress: float
    message: str
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str
    requested_by: Optional[str] = None
    trust_remote_code: bool = False
    license_accepted: bool = False
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    pin: bool = False
    force_redownload: bool = False
    pause_requested: bool = False
    cancel_requested: bool = False
    warnings: List[str] = Field(default_factory=list)
    detected_runtime: Optional[str] = None
    detected_modality: Optional[str] = None
    install_path: Optional[str] = None
    channel: Optional[DownloadChannelResponse] = None


class InstalledModelsResponse(BaseModel):
    models: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    statistics: Dict[str, Any] = Field(default_factory=dict)


class DiscoverySnapshotResponse(BaseModel):
    progress: Dict[str, Any] = Field(default_factory=dict)
    statistics: Dict[str, Any] = Field(default_factory=dict)


def _principal_payload(principal: Any) -> Dict[str, Any]:
    """Normalize authenticated principal metadata for service/audit contracts."""
    if isinstance(principal, Mapping):
        payload = dict(principal)
    else:
        payload = {}
        for key in ("user_id", "id", "username", "tenant_id", "roles", "scopes"):
            value = getattr(principal, key, None)
            if value is not None:
                payload[key] = value

    if not payload.get("user_id") and payload.get("id"):
        payload["user_id"] = payload["id"]
    return payload


def _model_dump(model: Any, *, exclude_none: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return dict(model.model_dump(exclude_none=exclude_none))
    if hasattr(model, "dict"):
        return dict(model.dict(exclude_none=exclude_none))
    raise TypeError(f"Unsupported request model: {type(model)!r}")


def _control_service():
    return get_model_download_control_service()


def get_orchestrator_service() -> ModelOrchestratorService:
    """Return the orchestrator owned by the canonical download control service.

    This compatibility accessor intentionally does not construct or configure a
    second orchestrator. All retained model lifecycle endpoints therefore share
    the same in-memory registry instance and persisted registry as downloads.
    """
    return _control_service()._orchestrator


async def get_current_user(request: Request) -> Dict[str, Any]:
    """Compatibility dependency overridden by the application runtime-admin gate."""
    principal = getattr(request.state, "user", None)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = _principal_payload(principal)
    payload.setdefault("roles", getattr(request.state, "roles", []) or [])
    payload.setdefault("scopes", getattr(request.state, "scopes", []) or [])
    return payload


def handle_orchestrator_error(error: ModelOrchestratorError) -> HTTPException:
    status_code_map = {
        E_NET: 503,
        E_DISK: 507,
        E_PERM: 403,
        E_LICENSE: 451,
        E_VERIFY: 422,
        E_SCHEMA: 422,
        E_COMPAT: 409,
        E_QUOTA: 507,
        E_NOT_FOUND: 404,
        E_INVALID: 400,
    }
    return HTTPException(
        status_code=status_code_map.get(error.code, 500),
        detail={
            "error_code": error.code,
            "message": error.message,
            "details": error.details,
        },
    )


def _serialize_download_job(job_payload: Optional[Dict[str, Any]]) -> DownloadJobResponse:
    if not job_payload:
        raise HTTPException(status_code=404, detail="Job not found")
    channel_payload = job_payload.get("channel")
    channel = DownloadChannelResponse(**channel_payload) if isinstance(channel_payload, dict) else None
    return DownloadJobResponse(
        job_id=job_payload["job_id"],
        model_id=job_payload["model_id"],
        revision=job_payload.get("revision"),
        channel_id=job_payload["channel_id"],
        storage_key=job_payload.get("storage_key"),
        status=job_payload["status"],
        progress=float(job_payload.get("progress") or 0.0),
        message=job_payload.get("message") or "",
        error=job_payload.get("error"),
        result=job_payload.get("result"),
        created_at=str(job_payload.get("created_at") or ""),
        updated_at=str(job_payload.get("updated_at") or ""),
        requested_by=job_payload.get("requested_by"),
        trust_remote_code=bool(job_payload.get("trust_remote_code", False)),
        license_accepted=bool(job_payload.get("license_accepted", False)),
        include_patterns=job_payload.get("include_patterns"),
        exclude_patterns=job_payload.get("exclude_patterns"),
        pin=bool(job_payload.get("pin", False)),
        force_redownload=bool(job_payload.get("force_redownload", False)),
        pause_requested=bool(job_payload.get("pause_requested", False)),
        cancel_requested=bool(job_payload.get("cancel_requested", False)),
        warnings=list(job_payload.get("warnings") or []),
        detected_runtime=job_payload.get("detected_runtime"),
        detected_modality=job_payload.get("detected_modality"),
        install_path=job_payload.get("install_path"),
        channel=channel,
    )


def _audit_model_removal(
    *,
    request: Request,
    principal: Any,
    model_id: str,
    delete_files: bool,
    outcome: str,
    error_code: Optional[str] = None,
) -> None:
    actor = _principal_payload(principal)
    client = getattr(request, "client", None)
    get_audit_logger().log_audit_event(
        {
            "event_type": "model_operation",
            "severity": "error" if outcome == "failed" else "info",
            "message": "model_remove",
            "user_id": str(actor.get("user_id") or actor.get("username") or "unknown"),
            "tenant_id": str(actor.get("tenant_id") or "") or None,
            "ip_address": getattr(client, "host", None),
            "user_agent": request.headers.get("user-agent"),
            "correlation_id": getattr(request.state, "correlation_id", None)
            or request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id"),
            "endpoint": request.url.path,
            "method": request.method,
            "metadata": {
                "model_id": model_id,
                "delete_files": delete_files,
                "outcome": outcome,
                "error_code": error_code,
            },
        }
    )


@router.get("/list/{owner}", response_model=List[ModelSummaryResponse])
async def list_models(
    owner: str,
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    sort: str = Query("downloads"),
    direction: int = Query(-1),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        models = await get_orchestrator_service().list_models(
            owner=owner,
            limit=limit,
            search=search,
            sort=sort,
            direction=direction,
        )
        return [
            ModelSummaryResponse(
                model_id=model.model_id,
                last_modified=model.last_modified,
                likes=model.likes,
                downloads=model.downloads,
                storage_key=model.storage_key,
                tags=model.tags,
                total_size=model.total_size,
                description=model.description,
            )
            for model in models
        ]
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list models for owner %s", owner)
        raise HTTPException(status_code=500, detail="Failed to list models") from exc


@router.get("/info/{model_id:path}", response_model=ModelInfoResponse)
async def get_model_info(
    model_id: str,
    revision: Optional[str] = Query(None),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        model_info = await get_orchestrator_service().get_model_info(model_id, revision)
        return ModelInfoResponse(
            model_id=model_info.model_id,
            owner=model_info.owner,
            repository=model_info.repository,
            storage_key=model_info.storage_key,
            files=model_info.files,
            total_size=model_info.total_size,
            last_modified=model_info.last_modified,
            downloads=model_info.downloads,
            likes=model_info.likes,
            tags=model_info.tags,
            license=model_info.license,
            description=model_info.description,
            revision=model_info.revision,
        )
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get model info for %s", model_id)
        raise HTTPException(status_code=500, detail="Failed to get model information") from exc


@router.post("/download", response_model=Dict[str, str])
async def download_model(
    download_request: ModelDownloadRequest,
    current_user: Any = Depends(get_current_user),
):
    try:
        job = await _control_service().start_download(
            _model_dump(download_request),
            _principal_payload(current_user),
        )
        return {
            "job_id": job["job_id"],
            "message": "Download queued",
            "status": job["status"],
        }
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to start model download for %s", download_request.model_id)
        raise HTTPException(status_code=500, detail="Failed to start model download") from exc


@router.delete("/remove/{model_id:path}", response_model=ModelRemoveResponse)
async def remove_model(
    model_id: str,
    request: Request,
    delete_files: bool = Query(True),
    current_user: Any = Depends(get_current_user),
):
    try:
        removal_result: RemoveResult = await get_orchestrator_service().remove_model(
            model_id=model_id,
            delete_files=delete_files,
        )
        _audit_model_removal(
            request=request,
            principal=current_user,
            model_id=model_id,
            delete_files=delete_files,
            outcome="succeeded",
        )
        return ModelRemoveResponse(
            model_id=removal_result.model_id,
            delete_files=delete_files,
            deleted_artifacts=removal_result.deleted_artifacts,
            warnings=removal_result.warnings,
            metadata=removal_result.metadata,
            message=f"Model {model_id} removed successfully",
        )
    except ModelOrchestratorError as exc:
        _audit_model_removal(
            request=request,
            principal=current_user,
            model_id=model_id,
            delete_files=delete_files,
            outcome="failed",
            error_code=exc.code,
        )
        raise handle_orchestrator_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _audit_model_removal(
            request=request,
            principal=current_user,
            model_id=model_id,
            delete_files=delete_files,
            outcome="failed",
            error_code="unexpected_error",
        )
        logger.exception("Failed to remove model %s", model_id)
        raise HTTPException(status_code=500, detail="Failed to remove model") from exc


@router.get("/download/channels", response_model=Dict[str, Any])
async def get_download_channels(current_user: Any = Depends(get_current_user)):
    del current_user
    return await _control_service().get_channels()


@router.get("/download/policy", response_model=DownloadPolicyResponse)
async def get_download_policy(current_user: Any = Depends(get_current_user)):
    del current_user
    return DownloadPolicyResponse(**(await _control_service().get_policy()))


@router.put("/download/policy", response_model=DownloadPolicyResponse)
async def update_download_policy(
    request: DownloadPolicyUpdateRequest,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    policy = await _control_service().update_policy(_model_dump(request, exclude_none=True))
    return DownloadPolicyResponse(**policy)


@router.post("/download/validate", response_model=DownloadValidationResponse)
async def validate_model_download(
    request: DownloadValidationRequest,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        validation = await _control_service().validate_download(
            model_id=request.model_id,
            revision=request.revision,
            channel_id=request.channel_id,
            trust_remote_code=request.trust_remote_code,
            accept_license=request.accept_license,
            include_patterns=request.include_patterns,
            exclude_patterns=request.exclude_patterns,
        )
        return DownloadValidationResponse(**validation.to_dict())
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc


@router.get("/download/jobs", response_model=List[DownloadJobResponse])
async def list_download_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    jobs = await _control_service().list_jobs(status=status, limit=limit)
    return [_serialize_download_job(job) for job in jobs]


@router.get("/download/jobs/{job_id}", response_model=DownloadJobResponse)
async def get_download_job(
    job_id: str,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    return _serialize_download_job(await _control_service().get_job(job_id))


@router.post("/download/jobs/{job_id}/cancel", response_model=DownloadJobResponse)
async def cancel_download_job(
    job_id: str,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        return _serialize_download_job(await _control_service().cancel_job(job_id))
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc


@router.post("/download/jobs/{job_id}/pause", response_model=DownloadJobResponse)
async def pause_download_job(
    job_id: str,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        return _serialize_download_job(await _control_service().pause_job(job_id))
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc


@router.post("/download/jobs/{job_id}/resume", response_model=DownloadJobResponse)
async def resume_download_job(
    job_id: str,
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        return _serialize_download_job(await _control_service().resume_job(job_id))
    except ModelOrchestratorError as exc:
        raise handle_orchestrator_error(exc) from exc


@router.get("/installed", response_model=InstalledModelsResponse)
async def get_installed_models(
    force_refresh: bool = Query(False),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    payload = await _control_service().get_installed_models(force_refresh=force_refresh)
    return InstalledModelsResponse(**payload)


@router.get("/discovery", response_model=DiscoverySnapshotResponse)
async def get_model_discovery_snapshot(
    force_refresh: bool = Query(False),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    payload = await _control_service().get_discovery_snapshot(force_refresh=force_refresh)
    return DiscoverySnapshotResponse(**payload)


@router.get("/health")
async def health_check():
    try:
        health = await get_model_orchestrator_health_checker().get_health_summary()
        return {
            "status": health["status"],
            "timestamp": health["timestamp"],
            "details": health,
        }
    except Exception as exc:
        logger.exception("Model orchestrator health check failed")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": type(exc).__name__,
        }


@router.get("/health/detailed")
async def detailed_health_check(current_user: Any = Depends(get_current_user)):
    del current_user
    try:
        return await get_model_orchestrator_health_checker().run_all_health_checks()
    except Exception as exc:
        logger.exception("Detailed model orchestrator health check failed")
        return {
            "overall_status": "critical",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": type(exc).__name__,
        }


@router.get("/metrics/summary")
async def metrics_summary(current_user: Any = Depends(get_current_user)):
    del current_user
    try:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": get_model_orchestrator_metrics().get_metrics_summary(),
        }
    except Exception as exc:
        logger.exception("Failed to get model orchestrator metrics")
        raise HTTPException(status_code=500, detail="Failed to get model metrics") from exc


@router.get("/errors/statistics")
async def error_statistics(
    hours: int = Query(24, ge=1, le=168),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "statistics": get_model_orchestrator_error_tracker().get_error_statistics(hours=hours),
        }
    except Exception as exc:
        logger.exception("Failed to get model orchestrator error statistics")
        raise HTTPException(status_code=500, detail="Failed to get model error statistics") from exc


@router.get("/errors/trends")
async def error_trends(
    days: int = Query(7, ge=1, le=30),
    current_user: Any = Depends(get_current_user),
):
    del current_user
    try:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trends": get_model_orchestrator_error_tracker().get_error_trends(days=days),
        }
    except Exception as exc:
        logger.exception("Failed to get model orchestrator error trends")
        raise HTTPException(status_code=500, detail="Failed to get model error trends") from exc

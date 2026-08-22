"""
Intelligent LLM Router API Routes

RETIRED: The IntelligentLLMRouter authority has migrated to
ChatRuntimeControlPlane / ProviderRouter. This module now returns
503/unavailable for retired endpoints instead of routing.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, HTTPException, Depends, Request = import_fastapi(
    "APIRouter", "HTTPException", "Depends", "Request"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

from ai_karen_engine.integrations.registry import get_registry
from ai_karen_engine.core.runtime.degraded_mode import get_degraded_mode_manager
from ai_karen_engine.core.model_runtime.production_decision_service import get_production_decision_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intelligent-router"])

RETIRED_MESSAGE = (
    "The legacy IntelligentLLMRouter is retired. "
    "Routing authority is ChatRuntimeControlPlane / ProviderRouter."
)


# Request/Response Models


class RoutingRequestModel(BaseModel):
    prompt: str = Field(description="Input prompt to route")
    task_type: str = Field(default="chat", description="Type of task")
    privacy_level: str = Field(default="public", description="Privacy level")
    performance_req: str = Field(default="interactive", description="Performance requirement")
    preferred_provider: Optional[str] = Field(default=None, description="Preferred provider")
    preferred_model: Optional[str] = Field(default=None, description="Preferred model")
    preferred_runtime: Optional[str] = Field(default=None, description="Preferred runtime")
    user_id: Optional[str] = Field(default=None, description="User ID")
    session_id: Optional[str] = Field(default=None, description="Session ID")
    context_length: Optional[int] = Field(default=None, description="Context length")
    requires_streaming: bool = Field(default=False, description="Requires streaming")
    requires_function_calling: bool = Field(default=False, description="Requires function calling")
    requires_vision: bool = Field(default=False, description="Requires vision capabilities")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RouteDecisionModel(BaseModel):
    provider: str = Field(description="Selected provider")
    runtime: str = Field(description="Selected runtime")
    model_id: str = Field(description="Selected model ID")
    reason: str = Field(description="Reason for selection")
    confidence: float = Field(description="Confidence score (0-1)")
    fallback_chain: List[str] = Field(description="Fallback chain")
    estimated_cost: Optional[float] = Field(description="Estimated cost")
    estimated_latency: Optional[float] = Field(description="Estimated latency")
    privacy_compliant: bool = Field(description="Privacy compliance")
    capabilities: List[str] = Field(description="Provider capabilities")
    fallback_level: int = Field(default=0, description="Fallback depth level")
    chosen_provider: Optional[str] = Field(default=None, description="Chosen provider")
    chosen_model: Optional[str] = Field(default=None, description="Chosen model")
    degraded_mode_reason: Optional[str] = Field(default=None, description="Degraded mode reason")


class DryRunAnalysisModel(BaseModel):
    request_summary: Dict[str, Any] = Field(description="Request summary")
    routing_steps: List[Dict[str, Any]] = Field(description="Routing analysis steps")
    available_providers: List[Dict[str, Any]] = Field(description="Available providers")
    available_runtimes: List[Dict[str, Any]] = Field(description="Available runtimes")
    policy_analysis: Dict[str, Any] = Field(description="Policy analysis")
    final_recommendation: Optional[Dict[str, Any]] = Field(description="Final recommendation")
    alternative_options: List[Dict[str, Any]] = Field(description="Alternative options")
    error: Optional[str] = Field(default=None, description="Error message")


class HealthStatusModel(BaseModel):
    summary: Dict[str, Any] = Field(description="Health summary")
    healthy_providers: List[str] = Field(description="Healthy providers")
    healthy_runtimes: List[str] = Field(description="Healthy runtimes")
    unhealthy_components: Dict[str, Any] = Field(description="Unhealthy components")
    recent_events: List[Dict[str, Any]] = Field(description="Recent health events")
    recent_failovers: List[Dict[str, Any]] = Field(description="Recent failovers")


class RoutingStatsModel(BaseModel):
    total_requests: int = Field(description="Total routing requests")
    successful_routes: int = Field(description="Successful routes")
    fallback_routes: int = Field(description="Fallback routes")
    degraded_routes: int = Field(description="Degraded mode routes")
    failed_routes: int = Field(description="Failed routes")
    active_policy: str = Field(description="Active routing policy")
    policy_weights: Dict[str, float] = Field(description="Policy weights")
    health_summary: Optional[Dict[str, Any]] = Field(default=None, description="Health summary")
    recent_health_events: Optional[int] = Field(default=None, description="Recent health events")
    recent_failovers: Optional[int] = Field(default=None, description="Recent failovers")


class PolicyInfoModel(BaseModel):
    name: str = Field(description="Policy name")
    description: str = Field(description="Policy description")
    weights: Dict[str, float] = Field(description="Policy weights")
    fallback_providers: List[str] = Field(description="Fallback providers")
    fallback_runtimes: List[str] = Field(description="Fallback runtimes")


class DegradedModeStatusModel(BaseModel):
    is_active: bool = Field(description="Whether degraded mode is active")
    reason: Optional[str] = Field(description="Reason for degraded mode")
    activated_at: Optional[str] = Field(description="When degraded mode was activated")
    failed_providers: List[str] = Field(description="Failed providers")
    recovery_attempts: int = Field(description="Number of recovery attempts")
    last_recovery_attempt: Optional[str] = Field(description="Last recovery attempt timestamp")
    core_helpers_available: Dict[str, bool] = Field(description="Core helpers availability")


# API Endpoints


@router.post("/route", response_model=RouteDecisionModel)
async def route_request(request: RoutingRequestModel) -> RouteDecisionModel:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.post("/dry-run", response_model=DryRunAnalysisModel)
async def dry_run_analysis(request: RoutingRequestModel) -> DryRunAnalysisModel:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.get("/health", response_model=HealthStatusModel)
async def get_health_status() -> HealthStatusModel:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.get("/stats", response_model=RoutingStatsModel)
async def get_routing_stats() -> RoutingStatsModel:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.post("/stats/reset")
async def reset_routing_stats() -> Dict[str, str]:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.get("/policy", response_model=PolicyInfoModel)
async def get_current_policy() -> PolicyInfoModel:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.get("/policies")
async def list_available_policies() -> Dict[str, List[str]]:
    return {"policies": []}


@router.post("/policy/{policy_name}")
async def set_routing_policy(policy_name: str) -> Dict[str, str]:
    raise HTTPException(
        status_code=503,
        detail=RETIRED_MESSAGE,
    )


@router.get("/degraded-mode", response_model=DegradedModeStatusModel)
async def get_degraded_mode_status() -> DegradedModeStatusModel:
    try:
        degraded_mode_manager = get_degraded_mode_manager()
        status = degraded_mode_manager.get_status()

        return DegradedModeStatusModel(
            is_active=status.is_active,
            reason=status.reason.value if status.reason else None,
            activated_at=status.activated_at.isoformat() if status.activated_at else None,
            failed_providers=status.failed_providers,
            recovery_attempts=status.recovery_attempts,
            last_recovery_attempt=status.last_recovery_attempt.isoformat() if status.last_recovery_attempt else None,
            core_helpers_available=status.core_helpers_available,
        )

    except Exception as e:
        logger.error(f"Degraded mode status check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Degraded mode status check failed: {str(e)}")


@router.post("/degraded-mode/recover")
async def attempt_degraded_mode_recovery() -> Dict[str, Any]:
    try:
        degraded_mode_manager = get_degraded_mode_manager()

        if not degraded_mode_manager.get_status().is_active:
            return {"message": "Degraded mode is not active", "recovery_needed": False}

        recovery_successful = degraded_mode_manager.attempt_recovery()

        return {
            "message": "Recovery attempt completed",
            "recovery_successful": recovery_successful,
            "recovery_attempts": degraded_mode_manager.get_status().recovery_attempts,
        }

    except Exception as e:
        logger.error(f"Degraded mode recovery failed: {e}")
        raise HTTPException(status_code=500, detail=f"Degraded mode recovery failed: {str(e)}")


@router.get("/providers")
async def list_providers(
    healthy_only: bool = False,
    category: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        registry = get_registry()
        provider_names = registry.list_providers(category=category, healthy_only=healthy_only)

        providers = []
        for name in provider_names:
            spec = registry.get_provider_spec(name)
            health = registry.get_health_status(f"provider:{name}")

            providers.append({
                "name": name,
                "description": spec.description if spec else "",
                "category": spec.category if spec else "unknown",
                "requires_api_key": spec.requires_api_key if spec else False,
                "capabilities": list(spec.capabilities) if spec else [],
                "health_status": health.status if health else "unknown",
                "last_health_check": health.last_check if health else None,
            })

        return {"providers": providers}

    except Exception as e:
        logger.error(f"Provider listing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Provider listing failed: {str(e)}")


@router.get("/runtimes")
async def list_runtimes(
    healthy_only: bool = False
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        registry = get_registry()
        runtime_names = registry.list_runtimes(healthy_only=healthy_only)

        runtimes = []
        for name in runtime_names:
            spec = registry.get_runtime_spec(name)
            health = registry.get_health_status(f"runtime:{name}")

            runtimes.append({
                "name": name,
                "description": spec.description if spec else "",
                "family": spec.family if spec else [],
                "supports": spec.supports if spec else [],
                "requires_gpu": spec.requires_gpu if spec else False,
                "memory_efficient": spec.memory_efficient if spec else False,
                "supports_streaming": spec.supports_streaming if spec else False,
                "supports_batching": spec.supports_batching if spec else False,
                "startup_time": spec.startup_time if spec else "unknown",
                "throughput": spec.throughput if spec else "unknown",
                "priority": spec.priority if spec else 50,
                "health_status": health.status if health else "unknown",
                "last_health_check": health.last_check if health else None,
            })

        return {"runtimes": runtimes}

    except Exception as e:
        logger.error(f"Runtime listing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Runtime listing failed: {str(e)}")


@router.get("/compatibility/{model_id}")
async def get_model_compatibility(
    model_id: str,
    provider: str,
    family: Optional[str] = None,
    format: Optional[str] = None
) -> Dict[str, List[str]]:
    try:
        from ai_karen_engine.integrations.registry import ModelMetadata

        registry = get_registry()

        model_meta = ModelMetadata(
            id=model_id,
            name=model_id,
            provider=provider,
            family=family or "",
            format=format or "",
        )

        compatible_runtimes = registry.compatible_runtimes(model_meta)
        optimal_runtime = registry.optimal_runtime(model_meta)

        return {
            "compatible_runtimes": compatible_runtimes,
            "optimal_runtime": optimal_runtime,
        }

    except Exception as e:
        logger.error(f"Compatibility check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Compatibility check failed: {str(e)}")


# Health check endpoint for the router itself
@router.get("/router/health")
async def router_health_check() -> Dict[str, Any]:
    try:
        health_info = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }

        try:
            registry = get_registry()
            provider_count = len(registry.list_providers())
            runtime_count = len(registry.list_runtimes())
            health_info["components"]["registry"] = {
                "status": "healthy",
                "providers": provider_count,
                "runtimes": runtime_count,
            }
        except Exception as e:
            health_info["components"]["registry"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health_info["status"] = "degraded"

        try:
            health_info["components"]["policy_manager"] = {
                "status": "retired",
                "detail": "Routing policy authority migrated to RuntimePolicyEnforcer",
            }
        except Exception as e:
            health_info["components"]["policy_manager"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health_info["status"] = "degraded"

        try:
            degraded_mode_manager = get_degraded_mode_manager()
            degraded_status = degraded_mode_manager.get_status()
            health_info["components"]["degraded_mode"] = {
                "status": "healthy",
                "is_active": degraded_status.is_active,
                "core_helpers_available": degraded_status.core_helpers_available,
            }
        except Exception as e:
            health_info["components"]["degraded_mode"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health_info["status"] = "degraded"

        return health_info

    except Exception as e:
        logger.error(f"Router health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


__all__ = ["router"]

"""
API Routes for KRO (Kari Reasoning Orchestrator)

Provides REST API endpoints for:
- Processing user requests through the canonical chat/runtime path
- Getting available models via canonical provider registry
- System status and health checks

DEPRECATED: Direct KRO/KIRE integration is retired.
Use ChatRuntime, ReasoningExecutor, WorkflowRuntime, and Medusa directly.
"""

from typing import Any, Dict, List, Optional
import logging

try:
    from fastapi import APIRouter, HTTPException, Body, Query
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class BaseModel:
        pass

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kro", tags=["kro"])


if FASTAPI_AVAILABLE:
    class UserRequestModel(BaseModel):
        """User request model."""
        user_input: str = Field(..., description="User's message or query")
        user_id: str = Field(default="anon", description="User identifier")
        conversation_history: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description="Recent conversation history"
        )
        context: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Additional context (session_id, tenant_id, etc.)"
        )

    class RoutingRequestModel(BaseModel):
        """Routing decision request."""
        user_input: str = Field(..., description="User's message or query")
        user_id: str = Field(default="anon", description="User identifier")
        task_type: Optional[str] = Field(default=None, description="Task type hint")
        context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")


@router.post("/process")
async def process_user_request(request: UserRequestModel):
    """
    Process user request through the governed chat runtime.

    Returns a standardized response envelope backed by the canonical chat path.
    """
    try:
        from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
        from ai_karen_engine.core.runtime.chat_runtime_contract import (
            ChatExecutionContext,
            ChatExecutionRequest,
        )

        runtime = get_chat_runtime()
        ctx = ChatExecutionContext(
            user_id=request.user_id,
            tenant_id=(request.context or {}).get("tenant_id", "default"),
            session_id=(request.context or {}).get("session_id"),
            conversation_id=(request.context or {}).get("conversation_id"),
            correlation_id=(request.context or {}).get("correlation_id"),
        )
        exec_request = ChatExecutionRequest(
            context=ctx,
            messages=[{"role": "user", "content": request.user_input}],
            metadata={
                "conversation_history": request.conversation_history or [],
                **(request.context or {}),
            },
        )
        result = await runtime.execute(exec_request)
        return {
            "success": result.status.value != "error",
            "message": result.answer,
            "meta": {
                "correlation_id": ctx.correlation_id,
                "latency_ms": result.metadata.latency_ms,
                "mode": result.metadata.mode,
                "degraded_mode": result.metadata.degraded_mode,
            },
        }

    except Exception as e:
        logger.error(f"KRO processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/process-specialized")
async def process_specialized_user_request(request: UserRequestModel):
    """
    Execute an explicit reasoning flow via ReasoningExecutor.

    This endpoint is intentionally out-of-band from the standard chat lifecycle.
    """
    try:
        from ai_karen_engine.core.reasoning.executor import get_reasoning_executor
        from ai_karen_engine.core.reasoning.contracts import (
            ReasoningBudget,
            ReasoningEvidence,
            ReasoningRequest,
        )
        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan,
            ExecutionBudget,
            ExecutionContext,
            ExecutionTopology,
        )

        executor = get_reasoning_executor()
        ctx = request.context or {}
        correlation_id = ctx.get("correlation_id") or str(__import__("uuid").uuid4())

        canonical_request = ReasoningRequest(
            request_id=correlation_id,
            correlation_id=correlation_id,
            tenant_id=ctx.get("tenant_id", "default"),
            user_id=request.user_id,
            conversation_id=ctx.get("conversation_id"),
            objective=request.user_input,
            reasoning_modes=["synthesis"],
            evidence=[],
            constraints={},
            policy_decision_id=correlation_id,
            budget=ReasoningBudget(),
            metadata={
                "conversation_history": request.conversation_history or [],
                **ctx,
            },
        )
        plan = AuthorizedExecutionPlan(
            execution_id=correlation_id,
            policy_decision_id=correlation_id,
            topology=ExecutionTopology.REASONING,
            budget=ExecutionBudget(
                max_duration_ms=30000,
                max_model_calls=3,
                max_reasoning_steps=5,
            ),
        )
        context = ExecutionContext(
            request_id=correlation_id,
            correlation_id=correlation_id,
            user_id=request.user_id,
            tenant_id=ctx.get("tenant_id", "default"),
        )
        result = await executor.execute(canonical_request, plan, context)

        return {
            "success": result.status not in ("failed", "budget_exhausted"),
            "message": result.conclusion,
            "reasoning_id": result.reasoning_id,
            "disposition": result.disposition,
            "diagnostics": result.diagnostics,
        }

    except Exception as e:
        logger.error(f"KRO specialized processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Specialized processing failed: {str(e)}")


@router.get("/models")
async def get_available_models():
    """
    Get list of all available models via canonical provider registry.
    """
    try:
        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )

        registry = get_provider_registry_service()
        providers = registry.get_all_provider_names()
        return {
            "success": True,
            "models": [],
            "count": 0,
            "providers": providers,
        }

    except Exception as e:
        logger.error(f"Model listing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get models: {str(e)}")


@router.post("/routing")
async def get_routing_decision(request: RoutingRequestModel):
    """
    Routing decision request is retired.

    CORTEX IntelligenceRuntime produces routing advisory signals.
    ProviderRouter owns provider selection.
    """
    raise HTTPException(
        status_code=410,
        detail="Routing decision endpoint is retired. Use CORTEX analysis and ProviderRouter directly.",
    )


@router.get("/status")
async def get_system_status():
    """System status is owned by the canonical runtime."""
    return {
        "status": "ok",
        "retired_endpoints": ["/api/kro/routing"],
        "canonical_paths": [
            "ChatRuntime.execute()",
            "ReasoningExecutor.execute()",
            "WorkflowRuntime.run()",
            "Medusa",
        ],
    }


@router.get("/health")
async def health_check():
    """Health check."""
    return {"status": "ok"}

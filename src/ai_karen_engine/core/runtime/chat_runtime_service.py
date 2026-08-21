from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, List

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_control_plane import get_chat_runtime_control_plane

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


class ChatRuntimeService:
    """Canonical chat runtime service for route-level orchestration helpers."""

    async def ensure_control_plane_ready(
        self,
        user_context: Optional[dict[str, Any]] = None,
        user_id: Optional[str] = None,
        message: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        """Ensure the control plane is ready for chat operations."""
        control_plane = await get_chat_runtime_control_plane()
        
        # Merge individual fields into context if provided
        ctx = dict(user_context or {})
        if user_id:
            ctx["user_id"] = user_id
        if message:
            ctx["message"] = message
        if session_id:
            ctx["session_id"] = session_id
        if correlation_id:
            ctx["correlation_id"] = correlation_id
            
        return await control_plane.get_runtime_response(user_context=ctx)

    async def get_orchestrator(self):
        """Legacy transport accessor. Prefer ``execute`` for new call sites.

        RC1.2 (LangGraph containment) will remove this; transports should
        delegate to :meth:`execute` / :meth:`execute_stream` instead.
        """
        from ai_karen_engine.core.langgraph_orchestrator import get_default_orchestrator

        return await get_default_orchestrator()

    async def execute(self, request: ChatExecutionRequest):
        """Delegate canonical chat execution to the single chat runtime."""
        return await get_chat_runtime().execute(request)

    async def execute_stream(self, request: ChatExecutionRequest):
        """Delegate canonical streaming chat execution to the single chat runtime."""
        return get_chat_runtime().execute_stream(request)

    async def build_router_fallback_assist_payload(
        self,
        *,
        request: Any,
        correlation_id: str,
        conversation_id: str,
        start_time: float,
        request_config_metadata: Dict[str, Any],
        actual_mode: str,
        transport: str,
        failure: Exception,
        streaming_enabled: bool = False,
        metadata_normalizer: Any,
    ) -> Optional[Dict[str, Any]]:
        """Use ExpressionGateway fallback when orchestration fails before answering.

        Runtime must only use ExpressionGateway for expression generation, not provider-specific routers.
        This ensures runtime remains decoupled from provider implementation details.
        """
        from ai_karen_engine.core.expression.gateway import ExpressionGateway
        from ai_karen_engine.core.expression.contracts import ExpressionTask

        gateway = ExpressionGateway()
        text = ""
        metadata: Dict[str, Any] = {}

        try:
            # Build ExpressionTask from request
            task = ExpressionTask(
                task_id=f"fallback_{correlation_id}",
                kind="fallback",
                correlation_id=correlation_id,
                request_id=correlation_id,
                messages=[{"role": "user", "content": request.message}],
                preferred_provider=request.preferred_llm_provider or None,
                preferred_model=request.preferred_model or None,
                max_tokens=120,
                temperature=0.7,
                timeout_ms=30000,
                required_capabilities=[],
                forbidden_capabilities=[],
                response_mode="text",
                metadata={
                    "fallback_reason": "orchestrator_error",
                    "orchestrator_error": str(failure)[:300],
                    "conversation_id": conversation_id,
                },
            )

            # Use ExpressionGateway for expression generation
            result = await gateway.generate(task)
            text = result.text or ""

            # Build metadata from ExpressionResult
            metadata.update({
                "requested_provider": request.preferred_llm_provider or "unknown",
                "requested_model": request.preferred_model or "auto",
                "actual_provider": result.provider,
                "actual_model": result.model,
                "engine_id": result.engine_id,
                "response_source": result.response_source,
                "latency_ms": result.latency_ms,
                "degraded": result.degraded,
                "degradation_reason": result.degradation_reason,
                "attempts": result.attempts,
                "skipped": result.skipped,
                "fallback_level": 1 if result.degraded else 0,
            })
        except Exception as gateway_error:
            logger.error("ExpressionGateway fallback failed after orchestrator error: %s", gateway_error, extra={"correlation_id": correlation_id})
            return None

        if not text.strip():
            return None

        response_metadata = metadata_normalizer(
            metadata=metadata,
            request=request,
            final_state=None,
            correlation_id=correlation_id,
            conversation_id=conversation_id,
            start_time=start_time,
            request_config_metadata=request_config_metadata,
            streaming_enabled=streaming_enabled,
            transport=transport,
            actual_response_mode=actual_mode,
        )
        response_metadata["orchestrator_error"] = {"type": type(failure).__name__, "message": str(failure)[:300]}

        return {"answer": text.strip(), "structured_content": {}, "actions": [], "metadata": response_metadata}

    def build_router_fallback_sse_events(self, payload: Dict[str, Any], correlation_id: str) -> List[Dict[str, Any]]:
        metadata = payload.get("metadata") or {}
        llm_metadata = metadata.get("llm") or {}
        requested_provider = llm_metadata.get("requested_provider")
        requested_model = llm_metadata.get("requested_model")
        actual_provider = llm_metadata.get("actual_provider")
        answer = str(payload.get("answer") or "").strip()

        events: List[Dict[str, Any]] = [{"type": "status", "content": "Selecting provider...", "correlation_id": correlation_id, "metadata": {**metadata, "status": "provider_selection", "requested_provider": requested_provider, "requested_model": requested_model}}]
        if requested_provider and actual_provider and str(requested_provider).lower() != str(actual_provider).lower():
            events.extend([
                {"type": "status", "content": "Requested provider unavailable; trying fallback.", "correlation_id": correlation_id, "metadata": {**metadata, "status": "provider_failed", "fallback_next": actual_provider}},
                {"type": "status", "content": f"Fallback provider selected: {actual_provider}", "correlation_id": correlation_id, "metadata": {**metadata, "status": "fallback_provider_selected"}},
            ])
        if answer:
            events.append({"type": "content", "content": answer, "correlation_id": correlation_id, "metadata": metadata})
        events.append({"type": "complete", "content": "", "correlation_id": correlation_id, "metadata": {**metadata, "status": "completed", "content_length": len(answer)}})
        return events


_chat_runtime_service: Optional[ChatRuntimeService] = None


def get_chat_runtime_service() -> ChatRuntimeService:
    global _chat_runtime_service
    if _chat_runtime_service is None:
        _chat_runtime_service = ChatRuntimeService()
    return _chat_runtime_service

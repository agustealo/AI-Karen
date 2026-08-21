from __future__ import annotations

import time
from typing import Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)

logger = get_logger(__name__)


async def build_runtime_fallback(
    *,
    runtime,
    request,
    failure: Exception,
    correlation_id: str,
    conversation_id: str,
    start_time: Optional[float] = None,
) -> Optional[ChatExecutionResult]:
    """Unified runtime fallback path (RC1.4).

    Collapses fallback into one owner: the runtime delegates to the
    ExpressionGateway fallback chain, then reports a degraded/emergency result
    through the single ``ChatRuntimeMetadata`` normalizer. No second
    independent router is started.

    Flow:
        requested execution
            -> ExpressionGateway fallback chain
            -> runtime degraded response
            -> emergency unavailable
    """
    ctx = request.context
    try:
        text, normalized = await runtime._run_simple(request)
    except Exception as fb_exc:  # pragma: no cover - defensive boundary
        logger.error(
            "Runtime fallback chain failed: %s",
            fb_exc,
            extra={"correlation_id": correlation_id},
        )
        text, normalized = "", {}

    if not (text and text.strip()):
        return None

    md = ChatRuntimeMetadata(
        correlation_id=correlation_id,
        latency_ms=(time.time() - (start_time or time.time())) * 1000.0,
        requested_provider=request.preferred_provider,
        requested_model=request.preferred_model,
        actual_provider=normalized.get("actual_provider"),
        actual_model=normalized.get("actual_model"),
        runtime_engine=normalized.get("runtime_engine"),
        response_source=normalized.get("response_source"),
        fallback_level=int(normalized.get("fallback_level") or 0) + 1,
        degraded_mode=True,
        degradation_reason=f"primary_failure:{type(failure).__name__}",
        mode="degraded",
        response_id=ctx.request_id,
        conversation_id=conversation_id,
    )
    # Preserve SSE/transport compatibility (provider identity under "llm").
    md.extra["llm"] = {
        "requested_provider": md.requested_provider,
        "actual_provider": md.actual_provider,
        "requested_model": md.requested_model,
        "actual_model": md.actual_model,
    }
    return ChatExecutionResult(
        answer=text,
        status=ChatExecutionStatus.DEGRADED,
        metadata=md,
    )

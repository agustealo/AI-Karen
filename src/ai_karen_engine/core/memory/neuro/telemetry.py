from __future__ import annotations

from typing import Any

from ai_karen_engine.core.logging import get_logger

logger = get_logger("kari.memory.neuro")

DEFAULT_EVENT_FIELDS: dict[str, Any] = {
    "correlation_id": None,
    "request_id": None,
    "tenant_id": None,
    "user_id": None,
    "session_id": None,
    "conversation_id": None,
    "intent": None,
    "memory_activation_mode": None,
    "memory_classes": [],
    "stores_queried": [],
    "store_latencies_ms": {},
    "result_count": 0,
    "selected_count": 0,
    "token_budget": None,
    "degraded": False,
    "degradation_reason": None,
    "circuit_breaker_state": None,
    "writeback_status": None,
}


def emit_memory_event(event: str, payload: dict[str, Any]) -> None:
    merged = {**DEFAULT_EVENT_FIELDS, **(payload or {})}
    logger.info(event, extra=merged)

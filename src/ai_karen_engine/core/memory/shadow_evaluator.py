"""Non-persisting memory formation evaluation.

Shadow mode evaluates the same signal and worthiness authorities used by
formation while explicitly withholding durable mutation. Runtime feature flags
decide when this evaluator is used; this module never owns flag policy.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.memory.scoring import MemoryWorthinessScorer
from ai_karen_engine.core.memory.signals import get_signal_pipeline


class MemoryShadowEvaluator:
    """Evaluate memory candidates without persistence or projection side effects."""

    def __init__(self) -> None:
        self._signal_pipeline = get_signal_pipeline()
        self._worthiness_scorer = MemoryWorthinessScorer()

    async def evaluate(
        self,
        *,
        text: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        normalized = str(text or "").strip()
        resolved_tenant = str(tenant_id or "").strip()
        resolved_user = str(user_id or "").strip()

        if not normalized:
            return {
                "status": "noop",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "empty_interaction",
            }
        if not resolved_tenant or not resolved_user:
            return {
                "status": "rejected",
                "extracted": 0,
                "admitted": 0,
                "persisted": 0,
                "reason": "missing_tenant_or_user_scope",
            }

        extraction = await self._signal_pipeline.process_text(
            text=normalized,
            tenant_id=resolved_tenant,
            user_id=resolved_user,
        )
        admitted = 0
        for signal in extraction.signals:
            worthiness = await self._worthiness_scorer.evaluate(
                signal.text,
                signal.signal_type,
            )
            if worthiness.get("is_worthy"):
                admitted += 1

        return {
            "status": "shadow",
            "extracted": len(extraction.signals),
            "admitted": admitted,
            "persisted": 0,
            "shadow_mode": True,
            "errors": list(extraction.errors),
            "processing_time_ms": extraction.processing_time_ms,
        }


__all__ = ["MemoryShadowEvaluator"]

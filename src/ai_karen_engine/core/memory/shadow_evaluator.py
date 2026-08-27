"""Non-persisting memory formation evaluation.

Shadow mode consumes the canonical formation evaluator and explicitly withholds
durable mutation. Runtime feature flags decide when this adapter is used; this
module never owns extraction, admission, persistence, projection, or flag policy.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.memory.formation.evaluator import MemoryFormationEvaluator


class MemoryShadowEvaluator:
    """Expose canonical formation evaluation without persistence side effects."""

    def __init__(self, evaluator: MemoryFormationEvaluator) -> None:
        self._evaluator = evaluator

    async def evaluate(
        self,
        *,
        text: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        evaluation = await self._evaluator.evaluate(
            text=text,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if evaluation.reason:
            return evaluation.summary(persisted=0)

        result = evaluation.summary(status="shadow", persisted=0)
        result["shadow_mode"] = True
        return result


__all__ = ["MemoryShadowEvaluator"]

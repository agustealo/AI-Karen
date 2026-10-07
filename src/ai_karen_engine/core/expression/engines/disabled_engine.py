from __future__ import annotations

from .base import BaseExpressionEngine
from ..contracts import EngineHealth, ExpressionResult, ExpressionTask
from ..errors import EngineUnavailableError


class DisabledEngine(BaseExpressionEngine):
    """Truthful adapter for a deliberately unavailable expression engine."""

    engine_id = "disabled"

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        raise EngineUnavailableError("Expression engine is disabled")

    async def health(self) -> EngineHealth:
        return EngineHealth(
            engine_id=self.engine_id,
            status="disabled",
            capabilities=[],
            models=[],
            reason="Expression engine is disabled",
        )

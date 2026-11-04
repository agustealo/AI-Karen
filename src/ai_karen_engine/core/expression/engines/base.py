from __future__ import annotations
from ..contracts import EngineHealth, ExpressionResult, ExpressionTask

class BaseExpressionEngine:
    engine_id = 'base'
    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        raise NotImplementedError
    async def health(self) -> EngineHealth:
        return EngineHealth(engine_id=self.engine_id, status='healthy', capabilities=[], models=[])

    async def generate_stream(self, task: ExpressionTask):
        """Fallback for engines without native token-stream support.

        This is a *single complete answer*, not simulated tokens. All engines
        can use one gateway stream contract while only capable endpoints send
        real incremental deltas.
        """
        from ..contracts import ExpressionStreamEvent

        result = await self.generate(task)
        if result.text:
            yield ExpressionStreamEvent(kind="delta", text_delta=result.text)
        yield ExpressionStreamEvent(kind="complete", result=result)

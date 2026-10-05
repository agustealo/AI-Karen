"""Runtime coordination for predictive continuity.

Runtime owns I/O and orchestration. CORTEX owns ranking decisions. This service
never executes a suggested action and never mutates memory.
"""

from __future__ import annotations

from datetime import datetime

from ai_karen_engine.core.cortex.continuity import (
    ContinuityPlan,
    ContinuityPlanner,
    ContinuityStatePort,
)


class ContinuityRuntime:
    """Fetch governed state and ask CORTEX to rank likely next needs."""

    def __init__(
        self,
        *,
        state_repository: ContinuityStatePort,
        planner: ContinuityPlanner | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._planner = planner or ContinuityPlanner()

    async def plan_next_actions(
        self,
        *,
        query: str,
        tenant_id: str,
        user_id: str,
        now: datetime | None = None,
        top_k: int = 5,
    ) -> ContinuityPlan:
        if not self._planner.should_plan(query):
            return ContinuityPlan(reason_codes=("continuity_not_requested",))

        items = await self._state_repository.list_current_state(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=max(top_k * 6, 30),
        )
        return self._planner.plan(
            query=query,
            items=items,
            now=now,
            top_k=top_k,
        )


__all__ = ["ContinuityRuntime"]

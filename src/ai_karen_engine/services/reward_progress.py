"""Application service for user reward/growth projections."""

from __future__ import annotations

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.intelligence.reward import RewardProgressSnapshot, RewardProjector
from ai_karen_engine.core.runtime.outcome.store import OutcomeStore, get_outcome_store


class RewardProgressError(RuntimeError):
    pass


class RewardProgressService:
    def __init__(
        self,
        *,
        store: OutcomeStore | None = None,
        projector: RewardProjector | None = None,
    ) -> None:
        self._store = store or get_outcome_store()
        self._projector = projector or RewardProjector()

    def snapshot(self, user: UserData, *, limit: int = 500) -> RewardProgressSnapshot:
        tenant_id = str(user.tenant_id or "").strip()
        user_id = str(user.user_id or "").strip()
        if not tenant_id or tenant_id == "default":
            raise RewardProgressError("Explicit tenant scope is required")
        if not user_id:
            raise RewardProgressError("Authenticated user scope is required")
        records = self._store.list_for_tenant(
            tenant_id,
            user_id=user_id,
            limit=max(1, min(limit, 1000)),
        )
        return self._projector.project(records)


_reward_progress_service: RewardProgressService | None = None


def get_reward_progress_service() -> RewardProgressService:
    global _reward_progress_service
    if _reward_progress_service is None:
        _reward_progress_service = RewardProgressService()
    return _reward_progress_service


__all__ = [
    "RewardProgressError",
    "RewardProgressService",
    "get_reward_progress_service",
]

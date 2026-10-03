"""Thin authenticated ingress for evidence-backed growth progress."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.reward_progress import (
    RewardProgressError,
    RewardProgressService,
    get_reward_progress_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/")
def get_my_progress(
    user: UserData = Depends(get_current_user),
    service: RewardProgressService = Depends(get_reward_progress_service),
) -> dict[str, Any]:
    try:
        return service.snapshot(user).to_dict()
    except RewardProgressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "reward.progress.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Growth progress is unavailable",
        ) from exc


__all__ = ["router"]

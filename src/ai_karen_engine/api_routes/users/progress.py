"""Thin authenticated ingress for evidence-backed growth progress."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.reward_progress import (
    RewardProgressError,
    RewardProgressService,
    get_reward_progress_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/progress", tags=["progress"])


class FeedbackRequest(BaseModel):
    trajectory_id: str = Field(..., min_length=1)
    feedback_type: Literal["thumbs_up", "thumbs_down"]
    message_id: str | None = None


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


@router.post("/feedback")
def record_feedback(
    request: FeedbackRequest,
    user: UserData = Depends(get_current_user),
    service: RewardProgressService = Depends(get_reward_progress_service),
) -> dict[str, Any]:
    try:
        payload = service.record_feedback(
            user,
            trajectory_id=request.trajectory_id,
            feedback_type=request.feedback_type,
            message_id=request.message_id,
        )
        return {
            "saved": True,
            "trajectory_id": request.trajectory_id,
            "feedback_type": request.feedback_type,
            "outcome_id": payload.get("outcome_id"),
        }
    except RewardProgressError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "reward.feedback.failed",
            extra={"user_id": user.user_id, "tenant_id": user.tenant_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Feedback could not be saved",
        ) from exc


__all__ = ["router"]

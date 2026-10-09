from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai_karen_engine.auth.rbac_middleware import Permission, require_permission
from ai_karen_engine.services.admin.admin_training_control_service import (
    AdminTrainingControlService,
)

router = APIRouter(prefix="/admin/training", tags=["admin-training"])


class TrainingControlPlaneResponse(BaseModel):
    architecture: dict[str, Any]
    prediction_tasks: list[str]
    lanes: list[dict[str, Any]]
    registry: dict[str, Any]
    governance: dict[str, Any]


class TrainingCapabilityResponse(BaseModel):
    lane_id: str
    title: str
    category: str
    authority: str
    module: str
    mode: str
    description: str
    human_like_role: str
    prediction_task: str | None = None
    available: bool
    model_count: int = 0
    active_model_count: int = 0
    shadow_model_count: int = 0
    candidate_model_count: int = 0


def get_admin_training_control_service() -> AdminTrainingControlService:
    return AdminTrainingControlService()


@router.get("/control-plane", response_model=TrainingControlPlaneResponse)
async def get_training_control_plane(
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_READ)
    ),
    service: AdminTrainingControlService = Depends(
        get_admin_training_control_service
    ),
) -> TrainingControlPlaneResponse:
    del current_user
    return TrainingControlPlaneResponse(**service.snapshot())


@router.get("/capabilities", response_model=list[TrainingCapabilityResponse])
async def list_training_capabilities(
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.ADMIN_READ)
    ),
    service: AdminTrainingControlService = Depends(
        get_admin_training_control_service
    ),
) -> list[TrainingCapabilityResponse]:
    del current_user
    snapshot = service.snapshot()
    return [TrainingCapabilityResponse(**lane) for lane in snapshot["lanes"]]

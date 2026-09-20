"""Consumer settings routes.

Installation/runtime configuration is not user preference state. Consumer-owned
behavior and notification preferences are persisted through the canonical auth
user record and are always scoped from the authenticated principal.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.user_prefs import UserPrefs, get_user_prefs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])


class BehaviorSettings(BaseModel):
    memoryDepth: Literal["short", "medium", "long"]
    personalityTone: Literal["neutral", "friendly", "formal", "humorous"]
    personalityVerbosity: Literal["concise", "balanced", "detailed"]
    activeListenMode: bool


class NotificationSettings(BaseModel):
    enabled: bool
    alertOnNewInsights: bool
    alertOnSummaryReady: bool


DEFAULT_BEHAVIOR_SETTINGS = BehaviorSettings(
    memoryDepth="medium",
    personalityTone="friendly",
    personalityVerbosity="balanced",
    activeListenMode=False,
)

DEFAULT_NOTIFICATION_SETTINGS = NotificationSettings(
    enabled=True,
    alertOnNewInsights=True,
    alertOnSummaryReady=True,
)


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[no-any-return]
    return model.dict()


async def _load_authoritative_user(current_user: UserData):
    """Load the authenticated user's durable record and verify tenant scope."""
    user_id = str(current_user.user_id or "").strip()
    tenant_id = str(current_user.tenant_id or "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user and tenant context are required",
        )

    auth_service = await get_auth_service()
    account = await auth_service.get_user_by_id(user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authenticated user record was not found",
        )

    if str(account.tenant_id or "").strip() != tenant_id:
        logger.error(
            "settings.user_tenant_mismatch",
            extra={
                "user_id": user_id,
                "principal_tenant_id": tenant_id,
                "record_tenant_id": account.tenant_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated tenant scope does not match the user record",
        )

    return auth_service, account


def _preference_section(
    preferences: Dict[str, Any],
    section: str,
    defaults: BaseModel,
) -> Dict[str, Any]:
    raw = preferences.get(section)
    if not isinstance(raw, dict):
        return _model_dump(defaults)

    merged = _model_dump(defaults)
    merged.update(raw)
    return merged


@router.get("/settings")
async def get_settings(
    user: UserPrefs = Depends(get_user_prefs),
    current_user: UserData = Depends(get_current_user),
):
    _, account = await _load_authoritative_user(current_user)
    return {
        "preferred_provider": user.preferred_provider,
        "preferred_model": user.preferred_model,
        "degraded_banner": user.show_degraded_banner,
        "degraded_status": user.degraded_status,
        "ui": user.ui,
        "active_profile": user.active_profile,
        "available_profiles": user.available_profiles,
        "profile_assignments": user.profile_assignments,
        "preferences": dict(account.preferences or {}),
    }


@router.get("/settings/behavior", response_model=BehaviorSettings)
async def get_behavior_settings(
    current_user: UserData = Depends(get_current_user),
):
    """Return behavior preferences for the authenticated user only."""
    _, account = await _load_authoritative_user(current_user)
    payload = _preference_section(
        dict(account.preferences or {}),
        "behavior",
        DEFAULT_BEHAVIOR_SETTINGS,
    )
    try:
        return BehaviorSettings(**payload)
    except Exception:
        logger.warning(
            "settings.behavior_invalid_persisted_value",
            extra={"user_id": current_user.user_id, "tenant_id": current_user.tenant_id},
        )
        return DEFAULT_BEHAVIOR_SETTINGS


@router.put("/settings/behavior")
async def update_behavior_settings(
    settings: BehaviorSettings,
    current_user: UserData = Depends(get_current_user),
):
    """Persist behavior preferences on the authenticated user's durable record."""
    auth_service, _ = await _load_authoritative_user(current_user)
    payload = _model_dump(settings)
    updated_user = await auth_service.update_user_preferences(
        user_id=str(current_user.user_id),
        preferences={"behavior": payload},
        merge=True,
    )
    if str(updated_user.tenant_id or "").strip() != str(current_user.tenant_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updated user tenant scope is invalid",
        )

    logger.info(
        "settings.behavior_updated",
        extra={"user_id": current_user.user_id, "tenant_id": current_user.tenant_id},
    )
    return {
        "status": "success",
        "message": "Behavior settings updated successfully",
        "behavior": payload,
    }


@router.get("/settings/notifications", response_model=NotificationSettings)
async def get_notification_settings(
    current_user: UserData = Depends(get_current_user),
):
    """Return notification preferences for the authenticated user only."""
    _, account = await _load_authoritative_user(current_user)
    payload = _preference_section(
        dict(account.preferences or {}),
        "notifications",
        DEFAULT_NOTIFICATION_SETTINGS,
    )
    try:
        return NotificationSettings(**payload)
    except Exception:
        logger.warning(
            "settings.notifications_invalid_persisted_value",
            extra={"user_id": current_user.user_id, "tenant_id": current_user.tenant_id},
        )
        return DEFAULT_NOTIFICATION_SETTINGS


@router.put("/settings/notifications")
async def update_notification_settings(
    settings: NotificationSettings,
    current_user: UserData = Depends(get_current_user),
):
    """Persist notification preferences on the authenticated user's durable record."""
    auth_service, _ = await _load_authoritative_user(current_user)
    payload = _model_dump(settings)
    updated_user = await auth_service.update_user_preferences(
        user_id=str(current_user.user_id),
        preferences={"notifications": payload},
        merge=True,
    )
    if str(updated_user.tenant_id or "").strip() != str(current_user.tenant_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Updated user tenant scope is invalid",
        )

    logger.info(
        "settings.notifications_updated",
        extra={"user_id": current_user.user_id, "tenant_id": current_user.tenant_id},
    )
    return {
        "status": "success",
        "message": "Notification settings updated successfully",
        "notifications": payload,
    }

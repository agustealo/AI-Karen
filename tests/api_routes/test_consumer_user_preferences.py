from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.system import settings as settings_routes
from ai_karen_engine.auth.models import UserData


class FakeAuthService:
    def __init__(
        self,
        *,
        user_id: str = "11111111-1111-1111-1111-111111111111",
        tenant_id: str = "tenant-a",
        preferences: Dict[str, Any] | None = None,
    ) -> None:
        self.account = SimpleNamespace(
            id=user_id,
            tenant_id=tenant_id,
            preferences=dict(preferences or {}),
        )
        self.preference_updates: list[Dict[str, Any]] = []

    async def get_user_by_id(self, user_id: str):
        if user_id != self.account.id:
            return None
        return self.account

    async def update_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any],
        *,
        merge: bool = True,
    ):
        self.preference_updates.append(
            {
                "user_id": user_id,
                "preferences": preferences,
                "merge": merge,
            }
        )
        current = dict(self.account.preferences)
        if merge:
            current.update(preferences)
        else:
            current = dict(preferences)
        self.account.preferences = current
        return self.account


def _principal(
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    tenant_id: str = "tenant-a",
) -> UserData:
    return UserData(
        user_id=user_id,
        tenant_id=tenant_id,
        email="consumer@example.com",
        roles=["user"],
    )


@pytest.mark.asyncio
async def test_behavior_preferences_are_loaded_from_durable_user_record(monkeypatch) -> None:
    service = FakeAuthService(
        preferences={
            "behavior": {
                "memoryDepth": "long",
                "personalityTone": "formal",
                "personalityVerbosity": "detailed",
                "activeListenMode": True,
            },
            "keep_me": {"value": 1},
        }
    )

    async def fake_get_auth_service():
        return service

    monkeypatch.setattr(settings_routes, "get_auth_service", fake_get_auth_service)

    result = await settings_routes.get_behavior_settings(_principal())

    assert result.memoryDepth == "long"
    assert result.personalityTone == "formal"
    assert result.personalityVerbosity == "detailed"
    assert result.activeListenMode is True


@pytest.mark.asyncio
async def test_behavior_update_targets_authenticated_user_and_preserves_other_sections(
    monkeypatch,
) -> None:
    service = FakeAuthService(
        preferences={
            "notifications": {
                "enabled": False,
                "alertOnNewInsights": False,
                "alertOnSummaryReady": True,
            }
        }
    )

    async def fake_get_auth_service():
        return service

    monkeypatch.setattr(settings_routes, "get_auth_service", fake_get_auth_service)

    payload = settings_routes.BehaviorSettings(
        memoryDepth="short",
        personalityTone="humorous",
        personalityVerbosity="concise",
        activeListenMode=True,
    )
    response = await settings_routes.update_behavior_settings(payload, _principal())

    assert response["status"] == "success"
    assert service.preference_updates == [
        {
            "user_id": "11111111-1111-1111-1111-111111111111",
            "preferences": {
                "behavior": {
                    "memoryDepth": "short",
                    "personalityTone": "humorous",
                    "personalityVerbosity": "concise",
                    "activeListenMode": True,
                }
            },
            "merge": True,
        }
    ]
    assert "notifications" in service.account.preferences
    assert service.account.preferences["behavior"]["memoryDepth"] == "short"


@pytest.mark.asyncio
async def test_notification_update_uses_same_user_preference_authority(monkeypatch) -> None:
    service = FakeAuthService()

    async def fake_get_auth_service():
        return service

    monkeypatch.setattr(settings_routes, "get_auth_service", fake_get_auth_service)

    payload = settings_routes.NotificationSettings(
        enabled=False,
        alertOnNewInsights=True,
        alertOnSummaryReady=False,
    )
    response = await settings_routes.update_notification_settings(payload, _principal())

    assert response["notifications"] == {
        "enabled": False,
        "alertOnNewInsights": True,
        "alertOnSummaryReady": False,
    }
    assert service.preference_updates[0]["user_id"] == _principal().user_id
    assert service.preference_updates[0]["merge"] is True


@pytest.mark.asyncio
async def test_tenant_mismatch_fails_closed_before_preference_write(monkeypatch) -> None:
    service = FakeAuthService(tenant_id="tenant-b")

    async def fake_get_auth_service():
        return service

    monkeypatch.setattr(settings_routes, "get_auth_service", fake_get_auth_service)

    payload = settings_routes.NotificationSettings(
        enabled=True,
        alertOnNewInsights=True,
        alertOnSummaryReady=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await settings_routes.update_notification_settings(payload, _principal())

    assert exc_info.value.status_code == 403
    assert service.preference_updates == []


def test_user_preference_routes_do_not_depend_on_global_settings_manager() -> None:
    source = settings_routes.__file__
    assert source
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()

    assert "SettingsManager" not in text
    assert "settings.json" not in text
    assert "update_user_preferences" in text
    assert "Depends(get_current_user)" in text

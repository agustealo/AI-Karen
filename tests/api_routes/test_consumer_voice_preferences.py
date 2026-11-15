"""Durable per-user voice selection must never impersonate plugin admin state."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.system import settings as routes
from ai_karen_engine.auth.models import UserData

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"


def principal(tenant=TENANT):
    return UserData(user_id=USER, tenant_id=tenant, roles=["user"])


class AuthService:
    def __init__(self, tenant=TENANT, preferences=None):
        self.record = SimpleNamespace(
            id=USER, tenant_id=tenant, preferences=dict(preferences or {}),
        )
        self.writes = []

    async def get_user_by_id(self, user_id):
        return self.record if user_id == USER else None

    async def update_user_preferences(self, user_id, preferences, *, merge=True):
        self.writes.append((user_id, preferences, merge))
        if merge:
            self.record.preferences.update(preferences)
        return self.record


def configure(monkeypatch, auth, engine_catalog=None):
    from ai_karen_engine.services import voice_runtime

    async def get_auth():
        return auth

    monkeypatch.setattr(routes, "get_auth_service", get_auth)
    catalog = engine_catalog or {
        "contract_version": "1.0.0",
        "engines": [{
            "engine_id": "pocket-tts",
            "voices": [{"id": "alba", "name": "Alba", "language": "en"}],
        }],
    }
    fake = SimpleNamespace(engine_catalog=lambda *args: ready(catalog))
    monkeypatch.setattr(voice_runtime, "get_voice_runtime", lambda: fake)
    return fake


async def ready(value):
    return value


@pytest.mark.asyncio
async def test_save_and_reload_scoped_voice_choice(monkeypatch):
    auth = AuthService(preferences={"behavior": {"memoryDepth": "long"}})
    configure(monkeypatch, auth)
    response = await routes.update_voice_settings(
        routes.VoiceSelectionSettings(engine_id="pocket-tts", voice_id="alba"),
        principal(),
    )
    assert response == {
        "status": "success",
        "voice": {"engine_id": "pocket-tts", "voice_id": "alba"},
        "available": True,
    }
    assert auth.writes == [(USER, {
        "voice": {"engine_id": "pocket-tts", "voice_id": "alba"},
    }, True)]
    assert (await routes.get_voice_settings(principal()))["available"] is True
    assert auth.record.preferences["behavior"]["memoryDepth"] == "long"


@pytest.mark.asyncio
async def test_unlisted_voice_and_engine_are_not_persisted(monkeypatch):
    auth = AuthService()
    configure(monkeypatch, auth)
    for engine, voice in (("other-tts", "alba"), ("pocket-tts", "invented")):
        with pytest.raises(HTTPException) as raised:
            await routes.update_voice_settings(
                routes.VoiceSelectionSettings(engine_id=engine, voice_id=voice),
                principal(),
            )
        assert raised.value.status_code == 422
    assert auth.writes == []


@pytest.mark.asyncio
async def test_reset_to_browser_speech_is_explicit_and_scope_safe(monkeypatch):
    auth = AuthService(preferences={
        "voice": {"engine_id": "pocket-tts", "voice_id": "alba"},
        "notifications": {"enabled": False},
    })
    configure(monkeypatch, auth)
    result = await routes.update_voice_settings(
        routes.VoiceSelectionSettings(engine_id=None, voice_id=None), principal(),
    )
    assert result["voice"] == {"engine_id": None, "voice_id": None}
    assert auth.record.preferences["notifications"]["enabled"] is False
    assert (await routes.get_voice_settings(principal()))["available"] is False


@pytest.mark.asyncio
async def test_unavailable_saved_engine_never_falls_back_silently(monkeypatch):
    auth = AuthService(preferences={"voice": {
        "engine_id": "pocket-tts", "voice_id": "alba",
    }})
    configure(monkeypatch, auth, engine_catalog={"contract_version": "1.0.0", "engines": []})
    result = await routes.get_voice_settings(principal())
    assert result["available"] is False
    assert result["voice"]["engine_id"] == "pocket-tts"
    assert not auth.writes


@pytest.mark.asyncio
async def test_tenant_switch_cannot_read_or_modify_other_users_voice(monkeypatch):
    auth = AuthService(tenant=OTHER_TENANT)
    configure(monkeypatch, auth)
    with pytest.raises(HTTPException) as read:
        await routes.get_voice_settings(principal())
    assert read.value.status_code == 403
    with pytest.raises(HTTPException) as write:
        await routes.update_voice_settings(
            routes.VoiceSelectionSettings(engine_id="pocket-tts", voice_id="alba"),
            principal(),
        )
    assert write.value.status_code == 403
    assert auth.writes == []


@pytest.mark.asyncio
async def test_partial_preference_is_not_persisted(monkeypatch):
    auth = AuthService()
    configure(monkeypatch, auth)
    with pytest.raises(HTTPException) as exc:
        await routes.update_voice_settings(
            routes.VoiceSelectionSettings(engine_id="pocket-tts", voice_id=None),
            principal(),
        )
    assert exc.value.status_code == 422
    assert auth.writes == []

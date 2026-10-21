"""Persona preference revision is part of the public typed API contract."""
from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from ai_karen_engine.api_routes.users.persona import (
    PreferencesResponse,
    UpdatePreferencesRequest,
    update_my_preferences,
)


def test_preference_request_excludes_revision_from_changes():
    request = UpdatePreferencesRequest(expected_revision=4, default_language="french")
    assert request.model_dump(exclude_unset=True, exclude={"expected_revision"}) == {
        "default_language": request.default_language,
    }
    with pytest.raises(ValidationError):
        UpdatePreferencesRequest(expected_revision=-1)


@pytest.mark.asyncio
async def test_stale_revision_maps_to_http_409(monkeypatch):
    import ai_karen_engine.api_routes.users.persona as routes

    class Service:
        async def update_user_preferences(self, **kwargs):
            assert kwargs["expected_revision"] == 5
            assert kwargs["updates"] == {"show_style_controls": False}
            raise ValueError("Persona preference revision conflict")

    monkeypatch.setattr(routes, "get_persona_service", lambda: Service())
    with pytest.raises(HTTPException) as error:
        await update_my_preferences(
            UpdatePreferencesRequest(expected_revision=5, show_style_controls=False),
            current_user={"user_id": "u", "tenant_id": "t"},
        )
    assert error.value.status_code == 409


def test_response_includes_revision():
    from ai_karen_engine.core.persona.contracts import UserPersonaPreferences

    model = UserPersonaPreferences(user_id="u", tenant_id="t", revision=6)
    response = PreferencesResponse(**model.model_dump(exclude={"custom_personas"}))
    assert response.revision == 6

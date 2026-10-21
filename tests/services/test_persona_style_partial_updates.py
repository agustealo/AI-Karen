"""Style preference writes must not overwrite a concurrent persona selection."""
import pytest
from ai_karen_engine.core.persona.contracts import UserPersonaPreferences
from pydantic import ValidationError
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_style_update_only_changes_requested_column():
    class Result:
        rowcount = 1

    class Session:
        async def execute(self, statement, values):
            sql = str(statement)
            assert "default_language = :default_language" in sql
            assert "active_persona_id =" not in sql
            assert "default_tone =" not in sql
            assert values["default_language"] == "french"
            return Result()

    class Context:
        async def __aenter__(self):
            return Session()
        async def __aexit__(self, *args):
            return False

    service = PersonaService.__new__(PersonaService)
    service._user_preferences_cache = {"tenant-a:user-a": object()}

    async def preferences(*args):
        return UserPersonaPreferences(user_id="user-a", tenant_id="tenant-a")

    service.get_user_preferences = preferences
    service._tenant_session = lambda tenant_id: Context()
    service._cache_key = lambda user_id, tenant_id: f"{tenant_id}:{user_id}"
    result = await service.update_user_preferences(
        "user-a", "tenant-a", {"default_language": "french"}
    )
    assert result.user_id == "user-a"
    assert "tenant-a:user-a" not in service._user_preferences_cache

@pytest.mark.asyncio
async def test_invalid_language_rejected_before_sql_write():
    service = PersonaService.__new__(PersonaService)
    async def preferences(*args):
        return UserPersonaPreferences(user_id="user-a", tenant_id="tenant-a")
    service.get_user_preferences = preferences
    with pytest.raises(ValidationError):
        await service.update_user_preferences(
            "user-a", "tenant-a", {"default_language": "fr_FR"}
        )

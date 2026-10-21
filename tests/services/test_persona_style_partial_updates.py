"""Style preference writes must not overwrite a concurrent persona selection."""
import pytest
from sqlalchemy import text
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
            assert values["default_language"] == "fr_FR"
            return Result()

    class Context:
        async def __aenter__(self):
            return Session()
        async def __aexit__(self, *args):
            return False

    service = PersonaService.__new__(PersonaService)
    service._user_preferences_cache = {"tenant-a:user-a": object()}

    async def preferences(*args):
        return "persisted"

    service.get_user_preferences = preferences
    service._tenant_session = lambda tenant_id: Context()
    service._cache_key = lambda user_id, tenant_id: f"{tenant_id}:{user_id}"
    result = await service.update_user_preferences(
        "user-a", "tenant-a", {"default_language": "fr_FR"}
    )
    assert result == "persisted"
    assert "tenant-a:user-a" not in service._user_preferences_cache

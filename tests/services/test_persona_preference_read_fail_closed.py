"""Persona preference load failures must never become default-row writes."""
import pytest

from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_missing_database_is_not_treated_as_missing_preferences():
    service = PersonaService.__new__(PersonaService)
    service.db_client = None
    with pytest.raises(RuntimeError, match="unavailable"):
        await service._load_user_preferences("user", "tenant")


@pytest.mark.asyncio
async def test_read_failure_propagates_without_initialization():
    service = PersonaService.__new__(PersonaService)
    service.db_client = object()
    writes = []

    class FailedSession:
        async def __aenter__(self):
            raise ValueError("corrupt persisted preferences")
        async def __aexit__(self, *args):
            return False

    service._tenant_session = lambda tenant_id: FailedSession()

    async def save(*args):
        writes.append(args)
        return True

    service._save_user_preferences = save
    with pytest.raises(RuntimeError, match="could not be loaded"):
        await service._load_user_preferences("user", "tenant")
    assert writes == []

"""Regression tests for canonical persona preference persistence failures."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.persona.contracts import UserPersonaPreferences
from ai_karen_engine.services.persona.persona_service import PersonaService


@pytest.mark.asyncio
async def test_missing_preference_storage_is_a_failure():
    service = object.__new__(PersonaService)
    service.db_client = None
    preferences = UserPersonaPreferences(user_id="owner", tenant_id="tenant")

    with pytest.raises(RuntimeError, match="persona_preferences_storage_unavailable"):
        await service._save_user_preferences("owner", "tenant", preferences)


@pytest.mark.asyncio
async def test_preference_write_exception_is_not_reported_as_success():
    service = object.__new__(PersonaService)
    service.db_client = object()
    preferences = UserPersonaPreferences(user_id="owner", tenant_id="tenant")

    @asynccontextmanager
    async def failed_session(tenant_id):
        session = AsyncMock()
        session.execute.side_effect = OSError("database disconnected")
        yield session

    service._tenant_session = failed_session

    with pytest.raises(RuntimeError, match="persona_preferences_write_failed"):
        await service._save_user_preferences("owner", "tenant", preferences)

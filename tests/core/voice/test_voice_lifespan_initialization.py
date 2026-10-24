"""Optional voice bootstrap stays in canonical lifespan and fails safely."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.server.startup import _initialize_optional_local_voice


@pytest.mark.asyncio
async def test_voice_lifespan_initializes_registered_engine_once():
    configure = AsyncMock(return_value=SimpleNamespace(
        status=SimpleNamespace(value="ready")
    ))
    with patch("ai_karen_engine.services.voice_runtime.configure_local_voice_runtime", configure):
        await _initialize_optional_local_voice()
    configure.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_voice_lifespan_does_not_crash_when_optional_model_fails():
    configure = AsyncMock(side_effect=RuntimeError("missing model"))
    with patch("ai_karen_engine.services.voice_runtime.configure_local_voice_runtime", configure):
        await _initialize_optional_local_voice()
    configure.assert_awaited_once_with()

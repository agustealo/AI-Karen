import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.agents.integration_service import AgentIntegrationService
from ai_karen_engine.agents.models import (
    AgentExecutionMode,
    AgentRequest,
    AgentResponse,
    AgentStatus,
)


class TestLegacyToMedusaDelegation:
    @pytest.mark.asyncio
    async def test_deep_agents_delegates_to_medusa(self):
        service = AgentIntegrationService()
        with patch.object(service, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(service, "_ensure_agent_registry", new_callable=AsyncMock, return_value=None):
                with patch("ai_karen_engine.agents.integration_service.get_capability_router") as mock_router:
                    mock_router.return_value.validate_request_feasibility = AsyncMock(return_value=(True, []))
                    mock_agent_info = MagicMock()
                    mock_agent_info.agent_id = "deep_agent_1"
                    mock_agent_info.name = "Deep Agent"
                    mock_agent_info.execution_mode = AgentExecutionMode.DEEP_AGENTS
                    mock_agent_info.status = AgentStatus.IDLE
                    mock_agent_info.capabilities = []
                    mock_agent_info.config = MagicMock()
                    mock_agent_info.config.custom_config = {}
                    mock_router.return_value.route_request = AsyncMock(return_value=(mock_agent_info, {}))
                    with patch("ai_karen_engine.agents.integration_service.MedusaAdapter") as MockMedusaAdapter:
                        mock_adapter = AsyncMock()
                        mock_adapter.execute.return_value = AgentResponse(
                            request_id="req-1",
                            agent_id="medusa",
                            execution_mode=AgentExecutionMode.DEEP_AGENTS,
                            response="Medusa synthesized result",
                            processing_time=1.5,
                            metadata={"delegated_to": "medusa"},
                        )
                        MockMedusaAdapter.return_value = mock_adapter

                        request = AgentRequest(
                            request_id="req-1",
                            message="complex multi-agent task",
                            execution_mode=AgentExecutionMode.DEEP_AGENTS,
                            session_id="session-1",
                            user_id="user-1",
                            capabilities_required=[],
                        )
                        response = await service.execute_request(request)

        assert response.response == "Medusa synthesized result"
        assert response.metadata.get("delegated_to") == "medusa"
        mock_adapter.execute.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_deep_agents_stream_delegates_to_medusa(self):
        service = AgentIntegrationService()
        with patch.object(service, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(service, "_ensure_agent_registry", new_callable=AsyncMock, return_value=None):
                with patch("ai_karen_engine.agents.integration_service.get_capability_router") as mock_router:
                    mock_router.return_value.validate_request_feasibility = AsyncMock(return_value=(True, []))
                    mock_agent_info = MagicMock()
                    mock_agent_info.agent_id = "deep_agent_2"
                    mock_agent_info.name = "Deep Agent"
                    mock_agent_info.execution_mode = AgentExecutionMode.DEEP_AGENTS
                    mock_agent_info.status = AgentStatus.IDLE
                    mock_agent_info.capabilities = []
                    mock_agent_info.config = MagicMock()
                    mock_agent_info.config.custom_config = {}
                    mock_router.return_value.route_request = AsyncMock(return_value=(mock_agent_info, {}))
                    with patch("ai_karen_engine.agents.integration_service.MedusaAdapter") as MockMedusaAdapter:
                        medusa_stream_response = MagicMock()
                        medusa_stream_response.request_id = "req-2"
                        medusa_stream_response.agent_id = "medusa"
                        medusa_stream_response.execution_mode = AgentExecutionMode.DEEP_AGENTS
                        medusa_stream_response.chunk = MagicMock()
                        medusa_stream_response.chunk.content = "streamed result"
                        medusa_stream_response.chunk.is_final = True
                        medusa_stream_response.is_complete = True
                        medusa_stream_response.metadata = {"delegated_to": "medusa"}

                        async def fake_stream(*args, **kwargs):
                            yield medusa_stream_response

                        mock_adapter = MagicMock()
                        mock_adapter.execute_stream = fake_stream
                        MockMedusaAdapter.return_value = mock_adapter

                        request = AgentRequest(
                            request_id="req-2",
                            message="complex streaming task",
                            execution_mode=AgentExecutionMode.DEEP_AGENTS,
                            session_id="session-2",
                            user_id="user-2",
                            capabilities_required=[],
                        )
                        chunks = [
                            chunk
                            async for chunk in service.execute_request_stream(request)
                        ]

        assert len(chunks) == 1
        assert chunks[0].chunk.content == "streamed result"
        assert chunks[0].metadata.get("delegated_to") == "medusa"

    @pytest.mark.asyncio
    async def test_native_mode_does_not_delegate_to_medusa(self):
        service = AgentIntegrationService()
        with patch.object(service, "_ensure_initialized", new_callable=AsyncMock):
            with patch.object(service, "_ensure_agent_registry", new_callable=AsyncMock, return_value=None):
                with patch("ai_karen_engine.agents.integration_service.get_capability_router") as mock_router:
                    mock_router.return_value.validate_request_feasibility = AsyncMock(return_value=(True, []))
                    mock_agent_info = MagicMock()
                    mock_agent_info.agent_id = "native_agent"
                    mock_agent_info.name = "Native Agent"
                    mock_agent_info.execution_mode = AgentExecutionMode.NATIVE
                    mock_agent_info.status = AgentStatus.IDLE
                    mock_agent_info.capabilities = []
                    mock_agent_info.config = MagicMock()
                    mock_agent_info.config.custom_config = {}
                    mock_router.return_value.route_request = AsyncMock(return_value=(mock_agent_info, {}))
                    with patch("ai_karen_engine.agents.integration_service.get_execution_handler") as mock_handler:
                        mock_handler.return_value.execute = AsyncMock(return_value=AgentResponse(
                            request_id="req-3",
                            agent_id="native_agent",
                            execution_mode=AgentExecutionMode.NATIVE,
                            response="native result",
                            processing_time=0.5,
                        ))
                        with patch("ai_karen_engine.agents.integration_service.MedusaAdapter") as MockMedusaAdapter:
                            request = AgentRequest(
                                request_id="req-3",
                                message="simple native task",
                                execution_mode=AgentExecutionMode.NATIVE,
                                session_id="session-3",
                                user_id="user-3",
                                capabilities_required=[],
                            )
                            response = await service.execute_request(request)
                            MockMedusaAdapter.assert_not_called()

        assert response.response == "native result"
        assert response.agent_id == "native_agent"

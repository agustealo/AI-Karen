import pytest
from unittest.mock import MagicMock, patch

def test_degraded_mode_no_llm_router():
    """Verify that generate_degraded_mode_response uses ExpressionGateway, not LLMRouter."""
    from ai_karen_engine.core.runtime.degraded_mode import generate_degraded_mode_response
    
    with patch("ai_karen_engine.core.expression.gateway.ExpressionGateway.generate") as mock_generate:
        mock_generate.return_value = MagicMock()
        mock_generate.return_value.text = "Mocked answer"
        mock_generate.return_value.provider = "mock_provider"
        mock_generate.return_value.model = "mock_model"
        mock_generate.return_value.engine_id = "mock_engine"
        mock_generate.return_value.response_source = "mock_source"
        mock_generate.return_value.latency_ms = 1.0
        mock_generate.return_value.degraded = False
        mock_generate.return_value.attempts = []
        mock_generate.return_value.skipped = []
        
        # We need to mock ResponseFormatterPipeline because it might fail on empty mocks
        with patch("ai_karen_engine.core.langgraph_orchestrator.formatting.response_formatter_pipeline.ResponseFormatterPipeline.build_response_envelope") as mock_build:
            mock_build.return_value = {"answer": "Mocked answer"}
            
            # This should NOT call LLMRouter
            with patch("ai_karen_engine.core.model_runtime.routing.llm_router_service.LLMRouter") as mock_router:
                import asyncio
                asyncio.run(generate_degraded_mode_response("hello"))
                
                assert mock_router.call_count == 0
                assert mock_generate.call_count == 1

def test_control_plane_no_llm_router():
    """Verify that ProviderRouterProbe uses ExpressionGateway, not LLMRouter."""
    from ai_karen_engine.core.runtime.chat_runtime_control_plane import ProviderRouterProbe
    
    probe = ProviderRouterProbe()
    
    with patch("ai_karen_engine.core.expression.gateway.ExpressionGateway.generate") as mock_generate:
        mock_generate.return_value = MagicMock()
        mock_generate.return_value.engine_id = "builtin"
        
        # This should NOT call LLMRouter
        with patch("ai_karen_engine.core.model_runtime.routing.llm_router_service.LLMRouter") as mock_router:
            import asyncio
            asyncio.run(probe.check())
            
            assert mock_router.call_count == 0
            assert mock_generate.call_count == 1


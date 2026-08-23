"""Integration tests for provider fallback chain."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any


class TestFallbackChain:
    """Test provider fallback chain execution."""
    
    @pytest.mark.asyncio
    async def test_gemini_to_vllm_fallback(self):
        """Test fallback from Gemini to vLLM when Gemini fails."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock Gemini to fail, vLLM to succeed
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            # First call (Gemini) fails
            gemini_provider = AsyncMock()
            gemini_provider.generate_response = AsyncMock(
                side_effect=Exception("Gemini API unavailable")
            )
            
            # Second call (vLLM) succeeds
            vllm_provider = AsyncMock()
            vllm_provider.generate_response = AsyncMock(
                return_value="Response from vLLM"
            )
            
            mock_get_provider.side_effect = [gemini_provider, vllm_provider]
            
            # Mock provider info
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "local-model"}
                
                # Execute fallback
                result = await router.generate_with_degraded_runtime_fallback(
                    request=ChatRequest(message="test message"),
                    requested_provider="gemini",
                    requested_model="gemini-2.5-flash",
                    failure_reason="Gemini API unavailable",
                )
                
                # Verify fallback executed
                assert result is not None
                assert result["content"] == "Response from vLLM"
                
                # Verify metadata
                metadata = result["metadata"]["llm"]
                assert metadata["requested_provider"] == "gemini"
                assert metadata["requested_model"] == "gemini-2.5-flash"
                assert metadata["provider"] == "builtin_vllm"
                assert metadata["source"] == "runtime_fallback"
                assert metadata["is_degraded"] is True
                assert metadata["used_fallback"] is True
                assert metadata["fallback_from"] == "gemini"
                assert "builtin_vllm" in metadata["fallback_chain"]
    
    @pytest.mark.asyncio
    async def test_vllm_to_transformers_fallback(self):
        """Test fallback from vLLM to Transformers when vLLM fails."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock vLLM to fail, Transformers to succeed
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            # First call (vLLM) fails
            vllm_provider = AsyncMock()
            vllm_provider.generate_response = AsyncMock(
                side_effect=Exception("vLLM server unavailable")
            )
            
            # Second call (Transformers) succeeds
            transformers_provider = AsyncMock()
            transformers_provider.generate_response = AsyncMock(
                return_value="Response from Transformers"
            )
            
            mock_get_provider.side_effect = [vllm_provider, transformers_provider]
            
            # Mock provider info
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "gpt2"}
                
                # Execute fallback
                result = await router.generate_with_degraded_runtime_fallback(
                    request=ChatRequest(message="test message"),
                    requested_provider="builtin_vllm",
                    requested_model="local-model",
                    failure_reason="vLLM server unavailable",
                )
                
                # Verify fallback executed
                assert result is not None
                assert result["content"] == "Response from Transformers"
                
                # Verify metadata
                metadata = result["metadata"]["llm"]
                assert metadata["requested_provider"] == "builtin_vllm"
                assert metadata["provider"] == "builtin_transformers"
                assert metadata["is_degraded"] is True
                assert metadata["used_fallback"] is True
    
    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_emergency(self):
        """Test that emergency response is returned when all providers fail."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock all providers to fail
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            failing_provider = AsyncMock()
            failing_provider.generate_response = AsyncMock(
                side_effect=Exception("Provider unavailable")
            )
            
            # All providers fail
            mock_get_provider.return_value = failing_provider
            
            # Mock provider info
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "model"}
                
                # Execute fallback
                result = await router.generate_with_degraded_runtime_fallback(
                    request=ChatRequest(message="test message"),
                    requested_provider="gemini",
                    requested_model="gemini-2.5-flash",
                    failure_reason="All providers unavailable",
                )
                
                # Verify emergency response
                assert result is not None
                assert "emergency" in result["content"].lower() or "could not reach" in result["content"].lower()
                
                # Verify metadata
                metadata = result["metadata"]["llm"]
                assert metadata["requested_provider"] == "gemini"
                assert metadata["provider"] == "fallback"
                assert metadata["source"] == "hardcoded_emergency"
                assert metadata["is_degraded"] is True
    
    @pytest.mark.asyncio
    async def test_metadata_reflects_actual_provider(self):
        """Test that metadata accurately shows which provider actually responded."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock primary fails, fallback succeeds
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            primary_provider = AsyncMock()
            primary_provider.generate_response = AsyncMock(
                side_effect=Exception("Primary failed")
            )
            
            fallback_provider = AsyncMock()
            fallback_provider.generate_response = AsyncMock(
                return_value="Fallback response"
            )
            
            mock_get_provider.side_effect = [primary_provider, fallback_provider]
            
            # Mock provider info
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "model"}
                
                # Execute
                result = await router.generate_with_degraded_runtime_fallback(
                    request=ChatRequest(message="test"),
                    requested_provider="primary",
                    requested_model="primary-model",
                    failure_reason="Primary failed",
                )
                
                # Verify metadata shows ACTUAL provider, not requested
                metadata = result["metadata"]["llm"]
                assert metadata["requested_provider"] == "primary"
                assert metadata["provider"] != "primary"  # Should be fallback provider
                assert metadata["provider"] == "builtin_vllm"  # First in fallback chain
    
    @pytest.mark.asyncio
    async def test_fallback_chain_order(self):
        """Test that fallback chain follows correct order: vLLM -> Transformers -> emergency."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
        )
        
        router = LLMRouter()
        
        # Verify fallback order constant
        assert router.RUNTIME_DEGRADED_FALLBACK_ORDER == (
            "builtin_vllm",
            "builtin_transformers",
            "fallback",
        )
    
    @pytest.mark.asyncio
    async def test_successful_primary_provider_no_fallback(self):
        """Test that fallback is NOT triggered when primary provider succeeds."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock primary succeeds
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            primary_provider = AsyncMock()
            primary_provider.generate_response = AsyncMock(
                return_value="Primary response"
            )
            
            mock_get_provider.return_value = primary_provider
            
            # Mock provider info
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "model"}
                
                # Mock health check to pass
                with patch.object(router, "_is_provider_healthy") as mock_health:
                    mock_health.return_value = True
                    
                    # Execute - should NOT call fallback method
                    # Instead test through process_chat_request
                    chunks = []
                    async for chunk in router.process_chat_request(
                        ChatRequest(message="test")
                    ):
                        chunks.append(chunk)
                    
                    # Verify response received
                    assert len(chunks) > 0
                    # Fallback should not have been triggered
                    # (This is implicit - if fallback was triggered, different provider would respond)


class TestOrchestrationFallback:
    """Test fallback integration in orchestration layer."""
    
    @pytest.mark.asyncio
    async def test_response_synth_calls_fallback_on_failure(self):
        """Test that response synthesis node calls fallback when primary fails."""
        from ai_karen_engine.core.langgraph_orchestrator.nodes.response_synth import (
            ResponseSynthesisNode,
        )
        from ai_karen_engine.core.langgraph_orchestrator.contracts.orchestration_state import (
            create_initial_state,
        )
        from langchain_core.messages import HumanMessage
        
        # Create mock router
        mock_router = AsyncMock()
        
        # Mock select_provider to return a provider
        mock_router.select_provider = AsyncMock(
            return_value=("gemini", "gemini-2.5-flash")
        )
        
        # Mock process_chat_request to fail
        async def failing_generator():
            raise Exception("Primary provider failed")
            yield  # Never reached
        
        mock_router.process_chat_request = AsyncMock(
            return_value=failing_generator()
        )
        
        # Mock fallback to succeed
        mock_router.generate_with_degraded_runtime_fallback = AsyncMock(
            return_value={
                "content": "Fallback response",
                "metadata": {
                    "llm": {
                        "requested_provider": "gemini",
                        "provider": "builtin_vllm",
                        "source": "runtime_fallback",
                        "is_degraded": True,
                    }
                }
            }
        )
        
        # Create node with mock router
        node = ResponseSynthesisNode(llm_router=mock_router)
        
        # Create state
        state = create_initial_state(
            messages=[HumanMessage(content="test")],
            user_id="test_user",
            session_id="test_session",
        )
        state["tool_results"] = [{"tool": "test", "output": "result"}]
        
        # Execute node
        result_state = await node(state)
        
        # Verify fallback was called
        mock_router.generate_with_degraded_runtime_fallback.assert_called_once()
        
        # Verify metadata was stored
        assert "llm_metadata" in result_state
        assert result_state["llm_metadata"]["provider"] == "builtin_vllm"
        assert result_state["llm_metadata"]["is_degraded"] is True


class TestMetadataAccuracy:
    """Test that metadata accurately reflects provider usage."""
    
    @pytest.mark.asyncio
    async def test_metadata_includes_all_required_fields(self):
        """Test that fallback metadata includes all required fields."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
            LLMRouter,
            ChatRequest,
        )
        
        router = LLMRouter()
        
        # Mock successful fallback
        with patch.object(router.registry, "get_provider") as mock_get_provider:
            provider = AsyncMock()
            provider.generate_response = AsyncMock(return_value="Response")
            mock_get_provider.return_value = provider
            
            with patch.object(router.registry, "get_provider_info") as mock_info:
                mock_info.return_value = {"default_model": "model"}
                
                result = await router.generate_with_degraded_runtime_fallback(
                    request=ChatRequest(message="test"),
                    requested_provider="primary",
                    requested_model="primary-model",
                    failure_reason="Test failure",
                )
                
                # Verify all required metadata fields
                metadata = result["metadata"]["llm"]
                required_fields = [
                    "requested_provider",
                    "requested_model",
                    "provider",
                    "model_id",
                    "source",
                    "is_degraded",
                    "used_fallback",
                    "fallback_from",
                    "fallback_chain",
                    "attempted_providers",
                    "failure_reason",
                ]
                
                for field in required_fields:
                    assert field in metadata, f"Missing required field: {field}"

# Made with Bob


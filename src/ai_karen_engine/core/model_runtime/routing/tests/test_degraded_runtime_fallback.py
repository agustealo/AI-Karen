"""
Tests for degraded runtime fallback in LLM Router.

These tests verify that when a requested provider fails, the system
properly falls back to builtin_transformers -> fallback
and returns correct metadata showing which provider actually answered.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
    LLMRouter,
    ChatRequest,
    ProviderPriority,
)


class TestDegradedRuntimeFallback:
    """Test suite for degraded runtime fallback functionality."""

    @pytest.fixture
    def router(self):
        """Create an LLMRouter instance for testing."""
        return LLMRouter()

    @pytest.fixture
    def mock_chat_request(self):
        """Create a mock chat request."""
        return ChatRequest(
            message="Hello, how are you?",
            conversation_id="test-conversation-123",
            platform="web",
            stream=False,
        )

    @pytest.mark.asyncio
    async def test_gemini_unavailable_fallback_to_transformers_succeeds(
        self, router, mock_chat_request
    ):
        """Test that when Gemini fails, Transformers fallback succeeds and returns proper metadata."""
        # Mock provider registry
        with patch.object(router, "registry") as mock_registry:
            # Mock get_provider_info for gemini (failed provider)
            gemini_info = {"default_model": "gemini-2.5-flash"}
            mock_registry.get_provider_info.side_effect = lambda name: (
                gemini_info if name == "gemini" else {"default_model": f"{name}-default"}
            )

            # Mock get_provider to return a mock Transformers provider
            mock_transformers_provider = MagicMock()
            mock_transformers_provider.generate_response = MagicMock(return_value="Hello from Transformers!")

            def get_provider_side_effect(name, model=None):
                if name == "builtin_transformers":
                    return mock_transformers_provider
                return None

            mock_registry.get_provider.side_effect = get_provider_side_effect

            # Mock _is_provider_healthy to only return True for builtin_transformers
            async def is_healthy_side_effect(name):
                return name in ["builtin_transformers", "fallback"]

            router._is_provider_healthy = AsyncMock(side_effect=is_healthy_side_effect)

            # Execute the fallback
            result = await router.generate_with_degraded_runtime_fallback(
                request=mock_chat_request,
                requested_provider="gemini",
                requested_model="gemini-2.5-flash",
                failure_reason="Gemini API key not configured",
            )

            # Verify the result
            assert "content" in result
            assert result["content"] == "Hello from Transformers!"

            # Verify metadata structure
            assert "metadata" in result
            assert "degraded_mode" in result["metadata"]
            assert result["metadata"]["degraded_mode"] is True

            # Verify LLM metadata
            llm_metadata = result["metadata"]["llm"]
            assert llm_metadata["requested_provider"] == "gemini"
            assert llm_metadata["requested_model"] == "gemini-2.5-flash"
            assert llm_metadata["provider"] == "builtin_transformers"
            assert llm_metadata["source"] == "runtime_fallback"
            assert llm_metadata["is_degraded"] is True
            assert llm_metadata["used_fallback"] is True
            assert llm_metadata["fallback_from"] == "gemini"
            assert llm_metadata["fallback_chain"] == [
                "builtin_transformers",
                "local_gguf",
                "fallback",
            ]
            assert "gemini" in llm_metadata["attempted_providers"]
            assert llm_metadata["failure_reason"] == "Gemini API key not configured"

            # The answer should NOT be the degraded warning
            assert result["content"] != "Requested provider gemini was unavailable; Karen continued in degraded mode."

    @pytest.mark.asyncio
    async def test_transformers_unavailable_fallback_emergency(
        self, router, mock_chat_request
    ):
        """Test that when Transformers fails, emergency fallback is used."""
        with patch.object(router, "registry") as mock_registry:
            # Mock get_provider_info
            mock_registry.get_provider_info.return_value = {
                "default_model": "fallback-model"
            }

            # Mock get_provider - all providers return None (unavailable)
            mock_registry.get_provider.return_value = None

            # Mock _is_provider_healthy - all providers unhealthy
            async def is_healthy_side_effect(name):
                return False

            router._is_provider_healthy = AsyncMock(side_effect=is_healthy_side_effect)

            # Execute the fallback
            result = await router.generate_with_degraded_runtime_fallback(
                request=mock_chat_request,
                requested_provider="builtin_transformers",
                requested_model="transformers-model",
                failure_reason="Transformers runtime not available",
            )

            # Verify the result uses emergency fallback
            assert "Emergency fallback response activated" in result["content"]
            assert result["metadata"]["llm"]["provider"] is None
            assert result["metadata"]["llm"]["actual_provider"] is None
            assert result["metadata"]["llm"]["source"] == "emergency_static"
            assert result["metadata"]["llm"]["model_id"] is None
            assert result["metadata"]["llm"]["provider_attempts"]

    @pytest.mark.asyncio
    async def test_metadata_provider_correct_when_transformers_answers(
        self, router, mock_chat_request
    ):
        """Test that metadata shows Transformers as the actual provider when it answers."""
        with patch.object(router, "registry") as mock_registry:
            # Mock get_provider_info
            mock_registry.get_provider_info.return_value = {
                "default_model": "qwen-local"
            }

            # Mock get_provider to return Transformers
            mock_transformers_provider = MagicMock()
            mock_transformers_provider.generate_response = MagicMock(
                return_value="Actual Transformers response text."
            )

            mock_registry.get_provider.side_effect = lambda name, model=None: (
                mock_transformers_provider if name == "builtin_transformers" else None
            )

            # Mock _is_provider_healthy
            router._is_provider_healthy = AsyncMock(return_value=True)

            # Execute the fallback
            result = await router.generate_with_degraded_runtime_fallback(
                request=mock_chat_request,
                requested_provider="gemini",
                requested_model="gemini-2.5-flash",
                failure_reason="Gemini unavailable",
            )

            # Verify metadata
            assert result["metadata"]["llm"]["requested_provider"] == "gemini"
            assert result["metadata"]["llm"]["provider"] == "builtin_transformers"
            assert result["metadata"]["llm"]["model_id"] == "qwen-local"
            assert result["metadata"]["llm"]["source"] == "runtime_fallback"

    @pytest.mark.asyncio
    async def test_attempted_providers_includes_failed_providers(
        self, router, mock_chat_request
    ):
        """Test that attempted_providers includes both failed provider and tried fallbacks."""
        with patch.object(router, "registry") as mock_registry:
            # Mock get_provider_info
            mock_registry.get_provider_info.return_value = {"default_model": "test-model"}

            # Mock get_provider to return None (all fail)
            mock_registry.get_provider.return_value = None

            # Mock _is_provider_healthy to return True but providers unavailable
            router._is_provider_healthy = AsyncMock(return_value=True)

            # Execute the fallback
            result = await router.generate_with_degraded_runtime_fallback(
                request=mock_chat_request,
                requested_provider="gemini",
                requested_model="gemini-2.5-flash",
                failure_reason="Gemini failed",
            )

            # Verify attempted_providers
            attempted = result["metadata"]["llm"]["attempted_providers"]
            assert "gemini" in attempted
            assert "builtin_transformers" in attempted

    @pytest.mark.asyncio
    async def test_invoke_provider_for_text_supports_generate_response(
        self, router, mock_chat_request
    ):
        """Test that _invoke_provider_for_text supports generate_response method."""
        mock_provider = MagicMock()
        mock_provider.generate_response = MagicMock(return_value="Test response")

        result = await router._invoke_provider_for_text(mock_provider, mock_chat_request)
        assert result == "Test response"
        mock_provider.generate_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_provider_for_text_supports_generate_text(
        self, router, mock_chat_request
    ):
        """Test that _invoke_provider_for_text supports generate_text method."""
        mock_provider = MagicMock()
        mock_provider.generate_text = MagicMock(return_value="Test response")
        del mock_provider.generate_response  # Remove generate_response

        result = await router._invoke_provider_for_text(mock_provider, mock_chat_request)
        assert result == "Test response"
        mock_provider.generate_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_provider_for_text_supports_chat(
        self, router, mock_chat_request
    ):
        """Test that _invoke_provider_for_text supports chat method."""
        mock_provider = MagicMock()
        mock_provider.chat = MagicMock(return_value="Test response")
        del mock_provider.generate_response
        del mock_provider.generate_text  # Remove other methods

        result = await router._invoke_provider_for_text(mock_provider, mock_chat_request)
        assert result == "Test response"
        mock_provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_provider_for_text_extracts_content_from_dict(
        self, router, mock_chat_request
    ):
        """Test that _invoke_provider_for_text extracts content from dict result."""
        mock_provider = MagicMock()
        mock_provider.generate_response = MagicMock(return_value={"content": "Extracted content"})

        result = await router._invoke_provider_for_text(mock_provider, mock_chat_request)
        assert result == "Extracted content"

    @pytest.mark.asyncio
    async def test_invoke_provider_for_text_handles_async_methods(
        self, router, mock_chat_request
    ):
        """Test that _invoke_provider_for_text handles async provider methods."""
        async def async_generate(text):
            return "Async response"

        mock_provider = MagicMock()
        mock_provider.generate_response = MagicMock(return_value=async_generate("test"))

        result = await router._invoke_provider_for_text(mock_provider, mock_chat_request)
        assert result == "Async response"

    def test_runtime_fallback_order_constant(self, router):
        """Test that the runtime fallback order constant is correct."""
        expected_order = ("builtin_transformers", "local_gguf", "fallback")
        assert router.RUNTIME_DEGRADED_FALLBACK_ORDER == expected_order


class TestProviderNormalization:
    """Test suite for provider name normalization."""

    def test_normalize_builtin_transformers_aliases(self):
        """Test that various Transformers aliases normalize to builtin_transformers."""
        router = LLMRouter()

        assert router._normalize_provider_name("transformers") == "builtin_transformers"
        assert router._normalize_provider_name("builtin_transformers") == "builtin_transformers"
        assert router._normalize_provider_name("hf_transformers") == "builtin_transformers"
        assert router._normalize_provider_name("hugging_face") == "builtin_transformers"
        assert router._normalize_provider_name("huggingface_local") == "builtin_transformers"

    def test_normalize_other_providers(self):
        """Test that other providers normalize correctly."""
        router = LLMRouter()

        assert router._normalize_provider_name("local") == "local_gguf"
        assert router._normalize_provider_name("openai") == "openai"
        assert router._normalize_provider_name("gemini") == "gemini"
        assert router._normalize_provider_name("anthropic") == "anthropic"

    def test_normalize_none_and_empty(self):
        """Test that None and empty strings return None."""
        router = LLMRouter()

        assert router._normalize_provider_name(None) is None
        assert router._normalize_provider_name("") is None
        assert router._normalize_provider_name("   ") is None

    def test_normalization_uses_canonical_registry_api(self, monkeypatch):
        router = LLMRouter()
        calls = {"count": 0}

        def _canonical(name):
            calls["count"] += 1
            return "builtin_transformers"

        monkeypatch.setattr(
            "ai_karen_engine.core.model_runtime.provider_registry_service.ProviderRegistryService.canonicalize_provider_id",
            staticmethod(_canonical),
        )
        assert router._normalize_provider_name("transformers") == "builtin_transformers"
        assert calls["count"] == 1


class TestProviderPriorities:
    """Test suite for provider priority mapping."""

    def test_builtin_transformers_has_transformer_priority(self):
        """Test that builtin_transformers has TRANSFORMER priority."""
        router = LLMRouter()
        assert router.provider_priorities["builtin_transformers"] == ProviderPriority.TRANSFORMER
        assert router.provider_priorities["transformers"] == ProviderPriority.TRANSFORMER

    def test_cloud_providers_have_remote_priority(self):
        """Test that cloud providers have REMOTE priority (lower than local)."""
        router = LLMRouter()
        assert router.provider_priorities["openai"] == ProviderPriority.REMOTE
        assert router.provider_priorities["gemini"] == ProviderPriority.REMOTE
        assert router.provider_priorities["anthropic"] == ProviderPriority.REMOTE
        assert router.provider_priorities["deepseek"] == ProviderPriority.REMOTE

    def test_fallback_has_lowest_priority(self):
        """Test that fallback has FALLBACK priority (lowest)."""
        router = LLMRouter()
        assert router.provider_priorities["fallback"] == ProviderPriority.FALLBACK

    def test_priority_order_respects_transformer_first(self):
        """Test that priority order respects transformer-first doctrine."""
        router = LLMRouter()
        transformer_priority = router.provider_priorities["builtin_transformers"]
        remote_priority = router.provider_priorities["gemini"]
        fallback_priority = router.provider_priorities["fallback"]

        assert transformer_priority.value < remote_priority.value
        assert remote_priority.value < fallback_priority.value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


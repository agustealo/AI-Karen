"""
Integration tests for VLLMRuntime adapter.

These tests verify that the vLLM adapter:
1. Raises ProviderNotAvailable when not configured
2. Generates text when vLLM is available
3. Does NOT silently fall back to other providers
4. Returns honest health check status
5. Properly handles streaming
6. Exposes accurate metadata
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import Mock

# Import VLLMRuntime and related classes
from ai_karen_engine.inference.vllm_runtime import VLLMRuntime
from ai_karen_engine.integrations.llm_utils import ProviderNotAvailable, GenerationFailed
from ai_karen_engine.integrations.providers.openai_provider import OpenAIProvider


class TestVLLMRuntimeConfig:
    """Test suite for VLLMRuntime configuration and initialization."""

    def test_vllm_runtime_without_base_url_uses_builtin_default(self, monkeypatch):
        """Test that VLLMRuntime defaults to the builtin vLLM endpoint."""
        monkeypatch.delenv("KAREN_BUILTIN_VLLM_BASE_URL", raising=False)
        monkeypatch.delenv("VLLM_BASE_URL", raising=False)
        monkeypatch.delenv("KAREN_VLLM_BASE_URL", raising=False)
        vllm = VLLMRuntime(model="test-model", base_url=None)

        assert vllm.base_url in {
            "http://vllm:8000/v1",
            "http://localhost:8001/v1",
        }

    def test_vllm_runtime_with_base_url_configured(self):
        """Test that VLLMRuntime can be initialized with a base_url."""
        vllm = VLLMRuntime(
            model="test-model",
            base_url="http://localhost:8001/v1"
        )

        assert vllm.base_url == "http://localhost:8001/v1"
        assert vllm.model == "test-model"
        assert vllm.provider_name == "builtin_vllm"

    def test_vllm_runtime_uses_env_variable(self, monkeypatch):
        """Test that VLLMRuntime reads canonical builtin vLLM env first."""
        # Set environment variable
        monkeypatch.setenv("KAREN_BUILTIN_VLLM_BASE_URL", "http://env-localhost:8001/v1")

        vllm = VLLMRuntime()

        assert vllm.base_url == "http://env-localhost:8001/v1"

    def test_vllm_runtime_singleton_pattern(self):
        """Test that VLLMRuntime uses singleton pattern correctly."""
        VLLMRuntime._instance = None
        instance1 = VLLMRuntime.get_instance(base_url="http://localhost:8001/v1")
        instance2 = VLLMRuntime.get_instance()

        assert instance1 is instance2

    def test_vllm_runtime_api_key_handling(self, monkeypatch):
        """Test that VLLMRuntime handles API keys correctly."""
        monkeypatch.setenv("VLLM_API_KEY", "test-api-key")

        vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

        assert vllm.api_key == "test-api-key"


class TestVLLMRuntimeHealthCheck:
    """Test suite for VLLMRuntime health check functionality."""

    def test_builtin_vllm_health_requires_models_endpoint(self, monkeypatch):
        monkeypatch.setenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME", "test-model")
        provider = OpenAIProvider(
            model="test-model",
            base_url="http://localhost:8001/v1",
            health_url="http://localhost:8001/health",
            provider_name="builtin_vllm",
        )
        provider.initialization_error = None

        def fake_get(url, timeout):
            response = MagicMock()
            if url.endswith("/health"):
                response.status_code = 200
                return response
            response.status_code = 503
            response.json.return_value = {}
            return response

        with patch("httpx.get", side_effect=fake_get):
            status = provider.health_check()

        assert status["status"] == "unhealthy"
        assert status["health_endpoint_ok"] is True
        assert status["models_endpoint_ok"] is False

    def test_builtin_vllm_health_requires_served_model(self, monkeypatch):
        monkeypatch.setenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME", "test-model")
        provider = OpenAIProvider(
            model="test-model",
            base_url="http://localhost:8001/v1",
            health_url="http://localhost:8001/health",
            provider_name="builtin_vllm",
        )
        provider.initialization_error = None

        def fake_get(url, timeout):
            response = MagicMock()
            response.status_code = 200
            if url.endswith("/models"):
                response.json.return_value = {"data": [{"id": "other-model"}]}
            return response

        with patch("httpx.get", side_effect=fake_get):
            status = provider.health_check()

        assert status["status"] == "unhealthy"
        assert status["models_endpoint_ok"] is True
        assert status["served_model_available"] is False

    def test_builtin_vllm_health_passes_when_endpoint_serves_model(self, monkeypatch):
        monkeypatch.setenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME", "test-model")
        provider = OpenAIProvider(
            model="test-model",
            base_url="http://localhost:8001/v1",
            health_url="http://localhost:8001/health",
            provider_name="builtin_vllm",
        )
        provider.initialization_error = None

        def fake_get(url, timeout):
            response = MagicMock()
            response.status_code = 200
            if url.endswith("/models"):
                response.json.return_value = {"data": [{"id": "test-model"}]}
            return response

        with patch("httpx.get", side_effect=fake_get):
            status = provider.health_check()

        assert status["status"] == "healthy"
        assert status["runtime_engine"] == "vllm"
        assert status["models_endpoint_ok"] is True
        assert status["served_model_available"] is True

    def test_health_check_with_base_url_calls_provider(self):
        """Test that health check delegates to OpenAI-compatible provider when configured."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider
            mock_provider = MagicMock()
            mock_provider.health_check.return_value = {
                "status": "healthy",
                "model": "test-model"
            }
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            status = vllm.health_check()

            # Verify provider was called
            mock_provider.health_check.assert_called_once()

            # Verify status structure
            assert status["provider"] == "builtin_vllm"
            assert status["runtime"] == "vllm"
            assert status["mode"] == "live_vllm"

    def test_health_check_with_provider_error_returns_unhealthy(self):
        """Test that health check returns unhealthy when provider raises exception."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider that raises error
            mock_provider = MagicMock()
            mock_provider.health_check.side_effect = Exception("Connection refused")
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            status = vllm.health_check()

            # Verify error status
            assert status["status"] == "unhealthy"
            assert status["mode"] == "unavailable"
            assert "error" in status
            assert "Connection refused" in status["error"]


class TestVLLMRuntimeGeneration:
    """Test suite for VLLMRuntime text generation."""

    def test_generate_with_base_url_calls_provider(self):
        """Test that generate() delegates to OpenAI-compatible provider when configured."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider
            mock_provider = MagicMock()
            mock_provider.generate_text.return_value = "Generated response from vLLM"
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            result = vllm.generate("Hello, vLLM!")

            # Verify provider was called
            mock_provider.generate_text.assert_called_once_with("Hello, vLLM!")

            # Verify result
            assert result == "Generated response from vLLM"

    def test_generate_with_provider_error_raises_generation_failed(self):
        """Test that generate() raises GenerationFailed when provider fails."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider that raises error
            mock_provider = MagicMock()
            mock_provider.generate_text.side_effect = Exception("API error")
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            with pytest.raises(GenerationFailed) as exc_info:
                vllm.generate("Hello, vLLM!")

            # Verify error message
            assert "vLLM generation failed" in str(exc_info.value)

    def test_generate_text_interface_method(self):
        """Test that generate_text() interface method delegates to generate()."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.generate_text.return_value = "Response"
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            result = vllm.generate_text("Test")

            assert result == "Response"

    def test_generate_response_interface_method(self):
        """Test that generate_response() interface method delegates to generate()."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.generate_text.return_value = "Response"
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            result = vllm.generate_response("Test")

            assert result == "Response"

    def test_no_silent_fallback_to_transformers(self):
        """Test that VLLMRuntime does NOT silently fall back to Transformers when vLLM fails."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider that fails
            mock_provider = MagicMock()
            mock_provider.generate_text.side_effect = Exception("vLLM unavailable")
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            # Should raise GenerationFailed, NOT return Transformers response
            with pytest.raises(GenerationFailed):
                vllm.generate("Test prompt")


class TestVLLMRuntimeStreaming:
    """Test suite for VLLMRuntime streaming functionality."""

    def test_stream_with_base_url_calls_provider(self):
        """Test that stream() delegates to OpenAI-compatible provider when configured."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider with streaming
            mock_provider = MagicMock()
            mock_provider.stream_generate.return_value = iter(["Hello", " from", " vLLM", "!"])
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            tokens = list(vllm.stream("Hello, vLLM!"))

            # Verify provider was called
            mock_provider.stream_generate.assert_called_once_with("Hello, vLLM!")

            # Verify tokens
            assert tokens == ["Hello", " from", " vLLM", "!"]

    def test_stream_with_provider_error_raises_generation_failed(self):
        """Test that stream() raises GenerationFailed when provider fails."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider that fails
            mock_provider = MagicMock()
            mock_provider.stream_generate.side_effect = Exception("Stream error")
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            with pytest.raises(GenerationFailed):
                list(vllm.stream("Test"))

    def test_stream_generate_interface_method(self):
        """Test that stream_generate() interface method delegates to stream()."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.stream_generate.return_value = iter(["Token"])
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            tokens = list(vllm.stream_generate("Test"))

            assert tokens == ["Token"]


class TestVLLMRuntimeEmbeddings:
    """Test suite for VLLMRuntime embedding functionality."""

    def test_embed_with_provider_support(self):
        """Test that embed() uses provider when embeddings are supported."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider with embed method
            mock_provider = MagicMock()
            mock_provider.embed.return_value = [0.1, 0.2, 0.3]
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            result = vllm.embed("test")

            # Verify provider was called
            mock_provider.embed.assert_called_once_with("test")
            assert result == [0.1, 0.2, 0.3]

    def test_embed_without_provider_support_raises_not_implemented(self):
        """Test that embed() raises NotImplementedError when provider doesn't support embeddings."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            # Setup mock provider without embed method
            mock_provider = MagicMock(spec=[])  # No methods
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            with pytest.raises(ProviderNotAvailable) as exc_info:
                vllm.embed("test")

            assert "vLLM embedding endpoint is not available" in str(exc_info.value)

    def test_embed_without_provider_support_does_not_use_transformers(self):
        """builtin_vllm must not silently map embeddings to Transformers."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class, \
             patch('ai_karen_engine.inference.transformers_runtime.TransformersRuntime.get_instance') as mock_transformers:
            mock_provider_class.return_value = MagicMock(spec=[])

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            with pytest.raises(ProviderNotAvailable):
                vllm.embed("test")
            mock_transformers.assert_not_called()


class TestVLLMRuntimeWarmCache:
    """Test suite for VLLMRuntime cache warming."""

    def test_warm_cache_calls_generate(self):
        """Test that warm_cache() calls generate with minimal request."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.generate_text.return_value = "ok"
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            # Should not raise exception
            vllm.warm_cache()

            # Verify it called generate_text with minimal prompt
            mock_provider.generate_text.assert_called_once_with("hello", max_tokens=1)

    def test_warm_cache_silently_fails(self):
        """Test that warm_cache() doesn't raise exceptions on failure."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.generate_text.side_effect = Exception("Server unavailable")
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")

            # Should not raise exception
            vllm.warm_cache()


class TestVLLMRuntimeModelLoading:
    """Test suite for VLLMRuntime model loading."""

    def test_load_model_updates_model_path(self):
        """Test that load_model() updates the model path."""
        vllm = VLLMRuntime(base_url="http://localhost:8001/v1", model="old-model")

        assert vllm.model == "old-model"

        # Load new model
        result = vllm.load_model("new-model")

        assert result is True
        assert vllm.model == "new-model"


class TestVLLMRuntimeMetadata:
    """Test suite for VLLMRuntime metadata accuracy."""

    def test_runtime_uses_correct_provider_name(self):
        """Test that VLLMRuntime uses the correct provider name in metadata."""
        vllm = VLLMRuntime(
            base_url="http://localhost:8001/v1",
            provider_name="builtin_vllm"
        )

        assert vllm.provider_name == "builtin_vllm"
        assert vllm._provider.provider_name == "builtin_vllm"
        assert vllm._provider.display_name == "vLLM"

    def test_health_check_includes_runtime_metadata(self):
        """Test that health check includes runtime metadata."""
        with patch('ai_karen_engine.inference.vllm_runtime.OpenAICompatibleProvider') as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider.health_check.return_value = {"status": "ok"}
            mock_provider_class.return_value = mock_provider

            vllm = VLLMRuntime(base_url="http://localhost:8001/v1")
            status = vllm.health_check()

            # Verify runtime metadata
            assert status["provider"] == "builtin_vllm"
            assert status["runtime"] == "vllm"
            assert status["mode"] == "live_vllm"


class TestVLLMRuntimeIntegration:
    """Integration tests for VLLMRuntime with the routing layer."""

    @pytest.mark.asyncio
    async def test_vllm_in_fallback_chain(self):
        """Test that VLLMRuntime properly integrates with the fallback chain."""
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import LLMRouter, ChatRequest

        router = LLMRouter()
        request = ChatRequest(
            message="Test message",
            conversation_id="test-123",
            platform="web",
            stream=False,
        )

        # This test verifies that VLLMRuntime raises ProviderNotAvailable
        # when vLLM is not running, allowing the router to fallback to a live provider
        with patch.object(router, "registry") as mock_registry:
            # Create mock VLLM instance that raises ProviderNotAvailable
            mock_vllm = MagicMock()
            mock_vllm.generate_response.side_effect = ProviderNotAvailable("vLLM not configured")

            # Create mock Ollama instance that succeeds
            mock_ollama = MagicMock()
            mock_ollama.generate_response.return_value = "Response from Ollama"

            def get_provider_side_effect(name):
                if name == "builtin_vllm":
                    return mock_vllm
                if name == "ollama":
                    return mock_ollama
                return None

            mock_registry.get_provider.side_effect = get_provider_side_effect
            def get_provider_info_side_effect(name):
                if name == "builtin_vllm":
                    return {
                        "default_model": "test-model",
                        "health_status": "degraded",
                        "runtime": "vllm",
                        "initialization_error": "connection refused",
                    }
                if name == "builtin_transformers":
                    return {
                        "default_model": "local-fallback",
                        "health_status": "healthy",
                        "runtime": "transformers",
                        "transformers_available": False,
                    }
                if name == "ollama":
                    return {
                        "default_model": "starcoder:128k",
                        "provider_type": "local",
                        "requires_api_key": False,
                        "available_models": ["starcoder:128k"],
                    }
                return {"default_model": "test-model"}

            mock_registry.get_provider_info.side_effect = get_provider_info_side_effect

            router._is_provider_healthy = AsyncMock(return_value=True)

            # Execute fallback - should skip vLLM and deterministic Transformers, then use Ollama.
            result = await router.generate_with_degraded_runtime_fallback(
                request=request,
                requested_provider="builtin_vllm",
                requested_model="test-model",
                failure_reason="vLLM unavailable"
            )

            assert result["metadata"]["llm"]["actual_provider"] == "ollama"
            assert result["metadata"]["llm"]["runtime_engine"] == "ollama"
            assert result["metadata"]["llm"]["response_source"] == "live_model"

    @pytest.mark.skipif(
        os.getenv("KAREN_RUN_VLLM_SMOKE") != "1",
        reason="vLLM smoke test requires KAREN_RUN_VLLM_SMOKE=1"
    )
    def test_vllm_smoke_test_with_real_server(self):
        """Smoke test that requires a real vLLM server to be running."""
        # This test only runs when KAREN_RUN_VLLM_SMOKE=1 is set
        base_url = os.getenv("KAREN_VLLM_BASE_URL", "http://localhost:8001/v1")
        model = os.getenv("KAREN_VLLM_MODEL", "test-model")

        vllm = VLLMRuntime(base_url=base_url, model=model)

        # Test health check
        health = vllm.health_check()
        assert health["configured"] is True
        assert health.get("status") != "unhealthy"

        # Test generation
        response = vllm.generate("Say vLLM smoke test passed in one sentence.")
        assert response
        assert isinstance(response, str)
        assert len(response) > 0
        assert "smoke test" in response.lower() or "passed" in response.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


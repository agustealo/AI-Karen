import pytest

from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderRouteDecision
from ai_karen_engine.services.models.routing.llm_router_service import ChatRequest
from ai_karen_engine.services.provider_runtime import ProviderRuntime


class _FakeProviderInfo:
    def __init__(self, default_model: str = "qwen3:4b"):
        self.default_model = default_model
        self.compatibility_profile = "ollama_compatible"
        self.available_models = [{"id": default_model, "name": default_model}]


class _FakeRegistry:
    def get_provider_info(self, provider_name: str):
        return _FakeProviderInfo()


class _SuccessRouter:
    def __init__(self):
        self.registry = _FakeRegistry()

    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        yield "ok"

    async def _generate_degraded_fallback(self, request, _unused, reason=""):
        return "emergency"

    async def _get_fallback_providers(self, current_provider, request):
        return []


class _FallbackRouter(_SuccessRouter):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        self.calls.append((provider_name, model_name))
        if provider_name == "gemini":
            raise RuntimeError("missing_api_key")
        yield "fallback text"

    async def _get_fallback_providers(self, current_provider, request):
        return ["ollama"]


class _EmergencyRouter(_SuccessRouter):
    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        raise AssertionError("no provider should be attempted when none is selected")


@pytest.mark.asyncio
async def test_execute_chat_returns_live_provider_metadata():
    runtime = ProviderRuntime(_SuccessRouter())
    decision = ProviderRouteDecision(
        requested_provider="gemini",
        requested_model="gemini-2.5-flash",
        selected_provider="gemini",
        selected_model="gemini-2.5-flash",
        provider_category="external",
        compatibility_profile="google_ai",
        runtime_engine="gemini",
        transport="http",
        selection_source="preferred",
        correlation_id="cid-1",
    )
    request = ChatRequest(message="hello", preferred_provider="gemini", preferred_model="gemini-2.5-flash")

    result = await runtime.execute_chat(decision, request)

    assert result.response_source == "provider_runtime"
    assert result.actual_provider == "gemini"
    assert result.actual_model == "gemini-2.5-flash"
    assert result.provider_attempts[0]["provider"] == "gemini"


@pytest.mark.asyncio
async def test_execute_chat_resolves_auto_to_concrete_model():
    runtime = ProviderRuntime(_SuccessRouter())
    decision = ProviderRouteDecision(
        requested_provider="ollama",
        requested_model="auto",
        selected_provider="ollama",
        selected_model="auto",
        provider_category="local",
        compatibility_profile="ollama_compatible",
        runtime_engine="ollama",
        transport="http",
        selection_source="preferred",
        correlation_id="cid-auto",
    )
    request = ChatRequest(message="hello", preferred_provider="ollama", preferred_model="auto")

    result = await runtime.execute_chat(decision, request)

    assert result.response_source == "provider_runtime"
    assert result.actual_provider == "ollama"
    assert result.actual_model == "qwen3:4b"
    assert result.actual_model != "auto"


@pytest.mark.asyncio
async def test_execute_chat_uses_concrete_fallback_model_and_no_auto():
    runtime = ProviderRuntime(_FallbackRouter())
    decision = ProviderRouteDecision(
        requested_provider="gemini",
        requested_model="gemini-2.5-flash",
        selected_provider="gemini",
        selected_model="gemini-2.5-flash",
        provider_category="external",
        compatibility_profile="google_ai",
        runtime_engine="gemini",
        transport="http",
        selection_source="preferred",
        correlation_id="cid-2",
    )
    request = ChatRequest(message="hello", preferred_provider="gemini", preferred_model="gemini-2.5-flash")

    result = await runtime.execute_chat(decision, request)

    assert result.response_source == "fallback_provider_runtime"
    assert result.actual_provider == "ollama"
    assert result.actual_model == "qwen3:4b"
    assert result.actual_model != "auto"
    assert any(attempt["provider"] == "gemini" for attempt in result.provider_attempts)
    assert any(attempt["provider"] == "ollama" and attempt["status"] == "success" for attempt in result.provider_attempts)


@pytest.mark.asyncio
async def test_execute_chat_emergency_static_when_no_provider_selected():
    runtime = ProviderRuntime(_EmergencyRouter())
    decision = ProviderRouteDecision(
        requested_provider="gemini",
        requested_model="gemini-2.5-flash",
        selected_provider=None,
        selected_model=None,
        provider_category="external",
        compatibility_profile="google_ai",
        runtime_engine="gemini",
        transport="http",
        selection_source="preferred",
        correlation_id="cid-3",
    )
    request = ChatRequest(message="hello", preferred_provider="gemini", preferred_model="gemini-2.5-flash")

    result = await runtime.execute_chat(decision, request)

    assert result.response_source == "emergency_static"
    assert result.actual_provider is None
    assert result.actual_model is None
    assert result.fallback_level == 99
    assert result.provider_attempts[0]["error_type"] == "provider_missing"

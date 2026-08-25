import pytest

from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderRouteDecision
from ai_karen_engine.core.model_runtime.routing.llm_router_service import ChatRequest
from ai_karen_engine.core.runtime.provider_runtime import ProviderRuntime


class _FakeProviderInfo:
    def __init__(self, default_model: str = "qwen3:4b"):
        self.default_model = default_model
        self.compatibility_profile = "ollama_compatible"
        self.available_models = [{"id": default_model, "name": default_model}]


class _FakeProvider:
    def __init__(self, name: str, should_fail: bool = False, response: str = "Hello! I am a simulated LLM provider. How can I help you today?"):
        self.name = name
        self.should_fail = should_fail
        self.response = response

    def generate_response(self, prompt: str, **kwargs):
        if self.should_fail:
            raise RuntimeError(f"simulated failure for {self.name}")
        return self.response

    def generate_text(self, prompt: str, **kwargs):
        if self.should_fail:
            raise RuntimeError(f"simulated failure for {self.name}")
        return self.response


class _FakeRegistry:
    def __init__(self, provider_models=None, failing_providers=None):
        self._provider_models = provider_models or {"gemini": "gemini-2.5-flash", "ollama": "qwen3:4b"}
        self._failing_providers = failing_providers or set()

    def get_provider_info(self, provider_name: str):
        return _FakeProviderInfo(default_model=self._provider_models.get(provider_name, "default"))

    def get_provider(self, name: str, **kwargs):
        should_fail = name in self._failing_providers
        return _FakeProvider(name, should_fail=should_fail)


class _SuccessRouter:
    def __init__(self):
        self.registry = _FakeRegistry()

    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        yield "ok"

    async def _generate_degraded_fallback(self, request, _unused, reason=""):
        return "emergency"

    async def _get_fallback_providers(self, current_provider, request):
        return []

    async def _get_available_providers_by_priority(self):
        return ["gemini", "ollama"]

    async def _is_provider_healthy(self, provider_name: str) -> bool:
        return True

    async def _meets_requirements(self, provider_name: str, request) -> bool:
        return True


class _FallbackRouter(_SuccessRouter):
    def __init__(self):
        self.registry = _FakeRegistry(failing_providers={"gemini"})
        self.calls = []

    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        self.calls.append((provider_name, model_name))
        if provider_name == "gemini":
            raise RuntimeError("missing_api_key")
        yield "fallback text"

    async def _get_fallback_providers(self, current_provider, request):
        return ["ollama"]

    async def _get_available_providers_by_priority(self):
        return ["gemini", "ollama"]

    async def _is_provider_healthy(self, provider_name: str) -> bool:
        return provider_name != "gemini"

    async def _meets_requirements(self, provider_name: str, request) -> bool:
        return True


class _EmergencyRouter(_SuccessRouter):
    async def _attempt_provider_with_retries(self, provider_name, request, request_id, model_name=None):
        raise AssertionError("no provider should be attempted when none is selected")


@pytest.mark.asyncio
async def test_execute_chat_returns_live_provider_metadata():
    runtime = ProviderRuntime(router=_SuccessRouter())
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
    runtime = ProviderRuntime(router=_SuccessRouter())
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
    runtime = ProviderRuntime(router=_FallbackRouter())
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

    assert result.response_source == "emergency_static"
    assert result.degraded_mode is True
    assert result.fallback_level == 99
    assert any(attempt["provider"] == "gemini" and attempt["status"] == "failed" for attempt in result.provider_attempts)


@pytest.mark.asyncio
async def test_execute_chat_emergency_static_when_no_provider_selected():
    runtime = ProviderRuntime(router=_EmergencyRouter())
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


@pytest.mark.asyncio
async def test_provider_runtime_does_not_call_llm_router_for_execution():
    router = _TrackingRouter()
    runtime = ProviderRuntime(router=router)
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
        correlation_id="cid-tracking",
    )
    request = ChatRequest(message="hello", preferred_provider="gemini", preferred_model="gemini-2.5-flash")

    result = await runtime.execute_chat(decision, request)

    assert result.response_source == "provider_runtime"
    assert not any(call[0] in ("_attempt_provider_with_retries", "_generate_degraded_fallback", "_get_fallback_providers") for call in router.execution_calls)


class _TrackingRouter:
    def __init__(self):
        self.registry = _FakeRegistry()
        self.execution_calls = []

    async def _attempt_provider_with_retries(self, *args, **kwargs):
        self.execution_calls.append(("_attempt_provider_with_retries", args, kwargs))
        raise AssertionError("ProviderRuntime should not call LLMRouter execution methods")

    async def _generate_degraded_fallback(self, *args, **kwargs):
        self.execution_calls.append(("_generate_degraded_fallback", args, kwargs))
        raise AssertionError("ProviderRuntime should not call LLMRouter execution methods")

    async def _get_fallback_providers(self, *args, **kwargs):
        self.execution_calls.append(("_get_fallback_providers", args, kwargs))
        raise AssertionError("ProviderRuntime should not call LLMRouter execution methods")

    async def _is_provider_healthy(self, *args, **kwargs):
        return True

    async def _meets_requirements(self, *args, **kwargs):
        return True

    async def _get_available_providers_by_priority(self):
        return ["gemini", "ollama"]

import pytest

from ai_karen_engine.core.model_runtime.production_decision_service import ProductionDecisionService


class _Status:
    def __init__(self, available=True, authenticated=True):
        self.available = available
        self.authenticated = authenticated


class FakeHealthChecker:
    async def check_single_provider(self, provider):
        if provider == "openai":
            return _Status(available=False, authenticated=False)
        return _Status(available=True, authenticated=True)


class FakeBaseRegistry:
    def get_provider_info(self, provider):
        return None


class FakeRegistry:
    def __init__(self):
        self.base_registry = FakeBaseRegistry()

    def select_provider_with_fallback(self, capability=None, fallback_chain_name=None):
        return "builtin_transformers"


@pytest.mark.asyncio
async def test_selection_is_identical_for_same_inputs_across_adapters():
    service = ProductionDecisionService(
        provider_registry=FakeRegistry(),
        health_checker=FakeHealthChecker(),
        config={"default_hierarchy": ["openai", "builtin_transformers"]},
    )

    route_a = await service.select({"provider": "openai", "model": "gpt-4"}, {"route": "intelligent-router"})
    route_b = await service.select({"provider": "openai", "model": "gpt-4"}, {"route": "intelligent-model"})

    assert route_a.provider == route_b.provider == "builtin_transformers"
    assert route_a.model == route_b.model == "auto"
    assert route_a.fallback_level == route_b.fallback_level
    assert route_a.fallback_chain == route_b.fallback_chain

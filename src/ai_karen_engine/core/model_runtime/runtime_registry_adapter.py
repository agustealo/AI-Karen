from __future__ import annotations

"""Compatibility façade for legacy Core consumers that expect an LLM registry.

This is not a second provider authority. It delegates all provider selection and
construction to the canonical Core ModelManager / ProviderRegistryService.
"""

from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
from ai_karen_engine.core.model_runtime.model_manager import get_model_manager


class RuntimeRegistryAdapter:
    def get_provider(self, name: str, **kwargs: Any) -> Any:
        del kwargs
        return LLMUtils(default=name).get_provider(name)

    def get_active(self) -> Any:
        return LLMUtils(default="auto").get_provider("auto")

    def get_available_providers(self) -> List[str]:
        return get_model_manager().registry.get_available_providers()

    def list_providers(self) -> List[str]:
        return self.get_available_providers()

    def auto_select_provider(self, requirements: Optional[Dict[str, Any]] = None) -> Optional[str]:
        return LLMUtils().auto_select_provider(requirements)

    def default_chain(self, healthy_only: bool = False) -> List[str]:
        del healthy_only
        return self.get_available_providers()

    def get_provider_info(self, name: str) -> Optional[Dict[str, Any]]:
        manager = get_model_manager()
        endpoint = manager.registry.get_provider_endpoint(name)
        if endpoint is None:
            return None
        return {
            "name": endpoint.provider_id,
            "display_name": endpoint.display_name,
            "base_url": endpoint.base_url,
            "default_model": endpoint.default_model,
            "capabilities": list(endpoint.capabilities),
            "runtime_engine": endpoint.runtime_engine.value,
            "locality": endpoint.locality.value,
        }

    def health_check(self, name: str) -> Dict[str, Any]:
        status = get_model_manager().registry.get_provider_status(name)
        if status is None:
            return {"status": "not_registered", "provider": name}
        return {
            "status": "healthy" if status.is_available else "unavailable",
            "provider": name,
            "health_status": status.health_status.value,
        }


_registry = RuntimeRegistryAdapter()


def get_registry() -> RuntimeRegistryAdapter:
    return _registry


def get_provider(name: str, **kwargs: Any) -> Any:
    return _registry.get_provider(name, **kwargs)

"""Model runtime domain for provider contracts and lazily loaded services."""

from __future__ import annotations

from .provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointStatus,
    ProviderEndpointType,
)

__all__ = [
    "AvailabilityStatus",
    "BUILTIN_PROVIDER_ENDPOINTS",
    "CacheEntry",
    "DiscoveryProgress",
    "DiscoveryStatus",
    "FallbackChain",
    "ModelCacheService",
    "ModelDiscoveryService",
    "ModelManager",
    "ModelMetadata",
    "ModelSummary",
    "PreloadPriority",
    "ProductionDecision",
    "ProductionDecisionService",
    "ProviderCapability",
    "ProviderEndpoint",
    "ProviderEndpointStatus",
    "ProviderEndpointType",
    "ProviderRegistryService",
    "ProviderStatus",
    "RuntimeSelection",
    "get_model_cache_service",
    "get_model_discovery_service",
    "get_model_manager",
    "get_production_decision_service",
    "get_provider_registry_service",
    "initialize_model_discovery_service",
    "initialize_model_manager",
    "initialize_provider_registry_service",
]

_LAZY_EXPORTS = {
    "DiscoveryProgress": (".model_discovery_service", "DiscoveryProgress"),
    "DiscoveryStatus": (".model_discovery_service", "DiscoveryStatus"),
    "ModelDiscoveryService": (".model_discovery_service", "ModelDiscoveryService"),
    "ModelSummary": (".model_discovery_service", "ModelSummary"),
    "get_model_discovery_service": (".model_discovery_service", "get_model_discovery_service"),
    "initialize_model_discovery_service": (".model_discovery_service", "initialize_model_discovery_service"),
    "ModelManager": (".model_manager", "ModelManager"),
    "RuntimeSelection": (".model_manager", "RuntimeSelection"),
    "get_model_manager": (".model_manager", "get_model_manager"),
    "initialize_model_manager": (".model_manager", "initialize_model_manager"),
    "ProductionDecision": (".production_decision_service", "ProductionDecision"),
    "ProductionDecisionService": (".production_decision_service", "ProductionDecisionService"),
    "get_production_decision_service": (".production_decision_service", "get_production_decision_service"),
    "FallbackChain": (".provider_registry_service", "FallbackChain"),
    "ProviderCapability": (".provider_registry_service", "ProviderCapability"),
    "ProviderRegistryService": (".provider_registry_service", "ProviderRegistryService"),
    "ProviderStatus": (".provider_registry_service", "ProviderStatus"),
    "get_provider_registry_service": (".provider_registry_service", "get_provider_registry_service"),
    "initialize_provider_registry_service": (".provider_registry_service", "initialize_provider_registry_service"),
    "AvailabilityStatus": (".model_cache_service", "AvailabilityStatus"),
    "CacheEntry": (".model_cache_service", "CacheEntry"),
    "ModelCacheService": (".model_cache_service", "ModelCacheService"),
    "ModelMetadata": (".model_cache_service", "ModelMetadata"),
    "PreloadPriority": (".model_cache_service", "PreloadPriority"),
    "get_model_cache_service": (".model_cache_service", "get_model_cache_service"),
}


def __getattr__(name: str):
    """Load service implementations only when explicitly requested."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)

    from importlib import import_module

    module_name, attribute_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value

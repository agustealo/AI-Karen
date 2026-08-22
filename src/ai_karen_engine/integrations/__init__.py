"""
Integration helpers for Kari AI.

Production-ready LLM integration system with:
- Multi-provider support (OpenAI, Gemini, local GGUF, HuggingFace, DeepSeek, etc.)
- Intelligent routing with capability awareness
- Fallback management (cloud → local → degraded)
- Error recovery and failure pattern analysis
- Model discovery and availability management
- Factory pattern for centralized initialization
"""

# Import factory for centralized initialization
from ai_karen_engine.integrations.factory import (
    IntegrationServiceConfig,
    IntegrationServiceFactory,
    get_integration_service_factory,
    get_provider_registry,
    get_llm_router,
    get_fallback_manager,
    initialize_integrations_for_production,
)

# Import dependencies for FastAPI dependency injection
from ai_karen_engine.integrations.dependencies import (
    get_provider_registry_dependency,
    get_llm_router_dependency,
    get_capability_router_dependency,
    get_copilot_router_dependency,
    get_fallback_manager_dependency,
    get_error_recovery_dependency,
    get_model_discovery_dependency,
    get_model_availability_manager_dependency,
    get_voice_registry_dependency,
    get_video_registry_dependency,
    get_confidence_scorer_dependency,
    get_task_analyzer_dependency,
    get_integration_health_check,
    get_best_available_router,
)

__all__ = [
    # Legacy compatibility
    "LocalRPAClient",
    "LLMProfileRouter",
    "ProviderRegistry",
    "ModelInfo",
    "get_voice_registry",
    "VoiceRegistry",
    "VoiceProviderBase",
    "DummyVoiceProvider",
    "OpenAIVoiceProvider",
    "VideoRegistry",
    "VideoProviderBase",
    "DummyVideoProvider",
    "OpenAIImageProvider",
    "get_video_registry",
    # Factory
    "IntegrationServiceConfig",
    "IntegrationServiceFactory",
    "get_integration_service_factory",
    # Factory convenience functions
    "get_provider_registry",
    "get_llm_router",
    "get_fallback_manager",
    "initialize_integrations_for_production",
    # Dependencies (FastAPI)
    "get_provider_registry_dependency",
    "get_llm_router_dependency",
    "get_capability_router_dependency",
    "get_copilot_router_dependency",
    "get_fallback_manager_dependency",
    "get_error_recovery_dependency",
    "get_model_discovery_dependency",
    "get_model_availability_manager_dependency",
    "get_voice_registry_dependency",
    "get_video_registry_dependency",
    "get_confidence_scorer_dependency",
    "get_task_analyzer_dependency",
    "get_integration_health_check",
    "get_best_available_router",
]


def __getattr__(name):
    if name == "LocalRPAClient":
        from ai_karen_engine.integrations.local_rpa_client import LocalRPAClient as _LocalRPAClient

        return _LocalRPAClient
    if name == "LLMProfileRouter":
        from ai_karen_engine.integrations.llm_router import LLMProfileRouter as _LLMProfileRouter

        return _LLMProfileRouter
    if name in {"ProviderRegistry", "ModelInfo", "get_provider_registry"}:
        from ai_karen_engine.integrations.provider_registry import (
            ProviderRegistry as _ProviderRegistry,
            ModelInfo as _ModelInfo,
            get_provider_registry as _get_provider_registry,
        )

        return {
            "ProviderRegistry": _ProviderRegistry,
            "ModelInfo": _ModelInfo,
            "get_provider_registry": _get_provider_registry,
        }[name]
    if name in {
        "VoiceRegistry",
        "VoiceProviderBase",
        "DummyVoiceProvider",
        "OpenAIVoiceProvider",
        "get_voice_registry",
    }:
        from ai_karen_engine.integrations.voice_registry import (
            VoiceRegistry as _VoiceRegistry,
            VoiceProviderBase as _VoiceProviderBase,
            DummyVoiceProvider as _DummyVoiceProvider,
            OpenAIVoiceProvider as _OpenAIVoiceProvider,
            get_voice_registry as _get_voice_registry,
        )

        return {
            "VoiceRegistry": _VoiceRegistry,
            "VoiceProviderBase": _VoiceProviderBase,
            "DummyVoiceProvider": _DummyVoiceProvider,
            "OpenAIVoiceProvider": _OpenAIVoiceProvider,
            "get_voice_registry": _get_voice_registry,
        }[name]
    if name in {
        "VideoRegistry",
        "VideoProviderBase",
        "DummyVideoProvider",
        "OpenAIImageProvider",
        "get_video_registry",
    }:
        from ai_karen_engine.integrations.video_registry import (
            VideoRegistry as _VideoRegistry,
            VideoProviderBase as _VideoProviderBase,
            DummyVideoProvider as _DummyVideoProvider,
            OpenAIImageProvider as _OpenAIImageProvider,
            get_video_registry as _get_video_registry,
        )

        return {
            "VideoRegistry": _VideoRegistry,
            "VideoProviderBase": _VideoProviderBase,
            "DummyVideoProvider": _DummyVideoProvider,
            "OpenAIImageProvider": _OpenAIImageProvider,
            "get_video_registry": _get_video_registry,
        }[name]
    raise AttributeError(name)

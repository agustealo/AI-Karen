"""
Integration helpers for Kari AI.

This package primarily contains external adapter/protocol boundaries.
Canonical runtime owners (provider routing, policy, fallback, task analysis,
prompt assembly) now live outside integrations.

Remaining integration concerns:
- External provider API adapters (OpenAI, Gemini, etc.)
- Media adapters (voice/video)
- CopilotKit boundary
- RPA/web retrieval adapters
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Genuine adapter imports
from ai_karen_engine.integrations.local_rpa_client import LocalRPAClient
from ai_karen_engine.integrations.nanda_client import NANDAClient
from ai_karen_engine.integrations.sr_llamaindex_adapter import LlamaIndexSRAdapter as SrLlamaIndexAdapter

# Voice/video registries retained as integration-boundary registries
from ai_karen_engine.integrations.voice_registry import (
    VoiceProviderBase,
    VoiceRegistry,
    get_voice_registry,
)
from ai_karen_engine.integrations.video_registry import (
    VideoProviderBase,
    VideoRegistry,
    get_video_registry,
)


__all__ = [
    "LocalRPAClient",
    "NANDAClient",
    "SrLlamaIndexAdapter",
    "VoiceRegistry",
    "VoiceProviderBase",
    "get_voice_registry",
    "VideoRegistry",
    "VideoProviderBase",
    "get_video_registry",
]


def __getattr__(name: str) -> Any:
    deprecated_legacy = {
        "ProviderRegistry",
        "ModelInfo",
        "DummyVoiceProvider",
        "OpenAIVoiceProvider",
        "DummyVideoProvider",
        "OpenAIImageProvider",
        "get_provider_registry",
    }
    if name in deprecated_legacy:
        logger.warning(
            "Deprecated integrations export '%s' accessed. "
            "Use canonical runtime owners instead.",
            name,
        )

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

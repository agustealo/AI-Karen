"""Reasoning synthesis public surface.

This package keeps compatibility exports for ICE and synthesis specialists, but
optional small-language-model runtime helpers are loaded only when explicitly
requested. Importing metacognition or refinement must not require system/runtime
dependencies such as psutil.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.reasoning.synthesis.ice_wrapper import (
    ICECircuitBreaker,
    ICEPerformanceBaseline,
    ICEWritebackPolicy,
    PremiumICEWrapper,
    ReasoningTrace,
    RecallStrategy,
    SynthesisMode,
)
from ai_karen_engine.core.reasoning.synthesis.metacognition import (
    CognitiveState,
    MetacognitiveConfig,
    MetacognitiveMonitor,
    MetacognitiveState,
    PerformanceMetrics,
    ReasoningStrategy,
)
from ai_karen_engine.core.reasoning.synthesis.self_refine import (
    FeedbackPoint,
    RefinementConfig,
    RefinementResult,
    RefinementStage,
    SelfRefiner,
    create_self_refiner,
)
from ai_karen_engine.core.reasoning.synthesis.subengines import (
    DSPySubEngine,
    LangGraphSubEngine,
    SynthesisSubEngine,
)

KariICEWrapper = PremiumICEWrapper

_OPTIONAL_SMALL_LM_EXPORTS = {
    "SmallLanguageModelService",
    "SmallLanguageModelConfig",
    "ModelInfo",
    "SystemResources",
    "ScaffoldResult",
    "OutlineResult",
    "SummaryResult",
    "SmallLMHealthStatus",
}


def __getattr__(name: str) -> Any:
    if name not in _OPTIONAL_SMALL_LM_EXPORTS:
        raise AttributeError(name)
    from ai_karen_engine.core.reasoning.synthesis import small_language_model_service

    value = getattr(small_language_model_service, name)
    globals()[name] = value
    return value


__all__ = [
    "PremiumICEWrapper",
    "KariICEWrapper",
    "ICEWritebackPolicy",
    "ReasoningTrace",
    "RecallStrategy",
    "SynthesisMode",
    "ICEPerformanceBaseline",
    "ICECircuitBreaker",
    "SynthesisSubEngine",
    "LangGraphSubEngine",
    "DSPySubEngine",
    "SelfRefiner",
    "RefinementConfig",
    "RefinementResult",
    "FeedbackPoint",
    "RefinementStage",
    "create_self_refiner",
    "MetacognitiveMonitor",
    "MetacognitiveState",
    "MetacognitiveConfig",
    "CognitiveState",
    "ReasoningStrategy",
    "PerformanceMetrics",
    "SmallLanguageModelService",
    "SmallLanguageModelConfig",
    "ModelInfo",
    "SystemResources",
    "ScaffoldResult",
    "OutlineResult",
    "SummaryResult",
    "SmallLMHealthStatus",
]

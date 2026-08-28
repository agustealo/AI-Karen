from __future__ import annotations

from typing import Any

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    IntelligenceSignal,
    SignalSourceType,
    SignalType,
    TaskAmbiguity,
    TaskComplexity,
    TaskRisk,
    TaskSignature,
)

__all__ = [
    "IntelligenceAnalysisResult",
    "IntelligenceRuntime",
    "IntelligenceSignal",
    "SignalSourceType",
    "SignalType",
    "TaskAmbiguity",
    "TaskComplexity",
    "TaskRisk",
    "TaskSignature",
    "get_intelligence_runtime",
]


def __getattr__(name: str) -> Any:
    """Lazy-load runtime exports so signal modules stay dependency-light."""
    if name == "IntelligenceRuntime":
        from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime

        return IntelligenceRuntime
    if name == "get_intelligence_runtime":
        from ai_karen_engine.core.intelligence.intelligence_runtime import (
            get_intelligence_runtime,
        )

        return get_intelligence_runtime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

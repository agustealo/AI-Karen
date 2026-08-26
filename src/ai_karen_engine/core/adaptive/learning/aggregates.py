"""Compatibility facade for historical adaptive performance aggregation.

Canonical performance-profile learning now lives in
``ai_karen_engine.core.intelligence.ml.performance_profiles``. Keep this module
only while existing adaptive imports are migrated.
"""

from ai_karen_engine.core.intelligence.ml.performance_profiles import (
    AgentPerformanceProfile,
    CapabilityPerformanceProfile,
    EvidenceAggregator,
    OutcomeObservation,
    PerformanceProfileAggregator,
)

__all__ = [
    "AgentPerformanceProfile",
    "CapabilityPerformanceProfile",
    "EvidenceAggregator",
    "OutcomeObservation",
    "PerformanceProfileAggregator",
]

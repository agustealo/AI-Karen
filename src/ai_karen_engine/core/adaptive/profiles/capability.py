"""Compatibility view for capability performance profiles.

Canonical derived capability-performance evidence lives in
``ai_karen_engine.core.intelligence.ml.performance_profiles``. Capability
availability/definition authority remains in the Core Capability Registry.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.intelligence.ml.performance_profiles import (
    CapabilityPerformanceProfile,
    EvidenceAggregator,
)


class CapabilityProfileStore:
    """Read-only compatibility view over capability performance profiles."""

    def __init__(self, aggregator: EvidenceAggregator | None = None) -> None:
        self._aggregator = aggregator or EvidenceAggregator()

    def get(self, capability_id: str) -> CapabilityPerformanceProfile:
        return self._aggregator.get_capability_profile(capability_id)

    def all(self) -> dict[str, CapabilityPerformanceProfile]:
        return self._aggregator.all_capability_profiles()

    def as_dict(self, capability_id: str) -> dict[str, Any]:
        profile = self.get(capability_id)
        return {
            "capability_id": profile.capability_id,
            "success_rate": profile.success_rate,
            "failure_rate": profile.failure_rate,
            "median_latency_ms": profile.median_latency_ms,
            "retry_rate": profile.retry_rate,
            "correction_rate": profile.correction_rate,
            "sample_count": profile.sample_count,
            "confidence_interval": profile.confidence_interval,
            "last_updated": profile.last_updated,
        }

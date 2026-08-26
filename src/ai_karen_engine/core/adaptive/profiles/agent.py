"""Compatibility view for agent performance profiles.

Canonical derived agent-performance evidence lives in
``ai_karen_engine.core.intelligence.ml.performance_profiles``. This module does
not own AgentMedusa registration semantics.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.intelligence.ml.performance_profiles import (
    AgentPerformanceProfile,
    EvidenceAggregator,
)


class AgentProfileStore:
    """Read-only compatibility view over agent performance profiles."""

    def __init__(self, aggregator: EvidenceAggregator | None = None) -> None:
        self._aggregator = aggregator or EvidenceAggregator()

    def get(self, agent_id: str) -> AgentPerformanceProfile:
        return self._aggregator.get_agent_profile(agent_id)

    def all(self) -> dict[str, AgentPerformanceProfile]:
        return self._aggregator.all_agent_profiles()

    def as_dict(self, agent_id: str) -> dict[str, Any]:
        profile = self.get(agent_id)
        return {
            "agent_id": profile.agent_id,
            "domain": profile.domain,
            "task_type": profile.task_type,
            "success_rate": profile.success_rate,
            "median_latency_ms": profile.median_latency_ms,
            "verification_success_rate": profile.verification_success_rate,
            "sample_count": profile.sample_count,
            "last_updated": profile.last_updated,
        }

"""Agent performance profiles.

Consumes AgentMedusa registration/execution metadata.
Creates derived profiles without modifying Medusa registry semantics.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.adaptive.contracts import AgentPerformanceProfile
from ai_karen_engine.core.adaptive.learning.aggregates import EvidenceAggregator


class AgentProfileStore:
    """Read-only view over agent performance profiles."""

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

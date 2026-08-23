"""Aggregate evidence store for adaptive learning.

Aggregates observations into capability/agent/model profiles.
Read-only views over historical data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ai_karen_engine.core.adaptive.contracts import (
    ActionOutcomeObservation,
    AgentPerformanceProfile,
    CapabilityPerformanceProfile,
)

logger = logging.getLogger(__name__)


class EvidenceAggregator:
    """Aggregates observations into performance profiles."""

    def __init__(self) -> None:
        self._observations: list[ActionOutcomeObservation] = []
        self._capability_profiles: dict[str, CapabilityPerformanceProfile] = {}
        self._agent_profiles: dict[str, AgentPerformanceProfile] = {}

    def add_observation(self, observation: ActionOutcomeObservation) -> None:
        """Add an observation for aggregation."""
        self._observations.append(observation)
        self._update_capability_profile(observation)
        self._update_agent_profile(observation)

    def get_capability_profile(self, capability_id: str) -> CapabilityPerformanceProfile:
        """Get performance profile for a capability."""
        return self._capability_profiles.get(
            capability_id,
            CapabilityPerformanceProfile(capability_id=capability_id),
        )

    def get_agent_profile(self, agent_id: str) -> AgentPerformanceProfile:
        """Get performance profile for an agent."""
        return self._agent_profiles.get(
            agent_id,
            AgentPerformanceProfile(agent_id=agent_id),
        )

    def all_capability_profiles(self) -> dict[str, CapabilityPerformanceProfile]:
        return dict(self._capability_profiles)

    def all_agent_profiles(self) -> dict[str, AgentPerformanceProfile]:
        return dict(self._agent_profiles)

    def _update_capability_profile(self, observation: ActionOutcomeObservation) -> None:
        action = observation.action_type
        target = observation.target_id or action
        key = f"{target}"
        if key not in self._capability_profiles:
            self._capability_profiles[key] = CapabilityPerformanceProfile(
                capability_id=key
            )
        profile = self._capability_profiles[key]
        profile.sample_count += 1
        if observation.execution_status == "success":
            profile.success_rate = self._ema(profile.success_rate, 1.0)
        else:
            profile.success_rate = self._ema(profile.success_rate, 0.0)
        profile.failure_rate = 1.0 - profile.success_rate
        profile.median_latency_ms = self._ema(
            profile.median_latency_ms, observation.latency_ms
        )
        if observation.fallback_used:
            profile.retry_rate = self._ema(profile.retry_rate, 1.0)
        if observation.correction:
            profile.correction_rate = self._ema(profile.correction_rate, 1.0)
        profile.last_updated = datetime.now(timezone.utc).isoformat()

    def _update_agent_profile(self, observation: ActionOutcomeObservation) -> None:
        action = observation.action_type
        if action not in ("use_agent", "use_multi_agent"):
            return
        target = observation.target_id or "unknown"
        if target not in self._agent_profiles:
            self._agent_profiles[target] = AgentPerformanceProfile(agent_id=target)
        profile = self._agent_profiles[target]
        profile.sample_count += 1
        if observation.execution_status == "success":
            profile.success_rate = self._ema(profile.success_rate, 1.0)
        else:
            profile.success_rate = self._ema(profile.success_rate, 0.0)
        profile.median_latency_ms = self._ema(
            profile.median_latency_ms, observation.latency_ms
        )
        profile.last_updated = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ema(current: float, new_value: float, alpha: float = 0.1) -> float:
        if current == 0.0 and new_value == 0.0:
            return 0.0
        if current == 0.0:
            return new_value
        return current + alpha * (new_value - current)

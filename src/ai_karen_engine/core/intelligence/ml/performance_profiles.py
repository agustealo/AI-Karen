"""Canonical performance-profile learning primitives.

This module owns derived agent/capability performance summaries used by
Intelligence/ML. It does not modify AgentMedusa registrations, capability
registry authority, runtime policy, or execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


class OutcomeObservation(Protocol):
    """Structural contract for historical execution outcomes.

    Runtime/adaptive compatibility records may satisfy this protocol without
    importing Intelligence implementation types.
    """

    action_type: str
    target_id: str | None
    execution_status: str
    latency_ms: float
    fallback_used: bool
    correction: bool


@dataclass(slots=True)
class CapabilityPerformanceProfile:
    capability_id: str
    success_rate: float = 0.0
    failure_rate: float = 0.0
    median_latency_ms: float = 0.0
    retry_rate: float = 0.0
    correction_rate: float = 0.0
    sample_count: int = 0
    confidence_interval: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentPerformanceProfile:
    agent_id: str
    domain: str = ""
    task_type: str = ""
    success_rate: float = 0.0
    median_latency_ms: float = 0.0
    verification_success_rate: float = 0.0
    sample_count: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class PerformanceProfileAggregator:
    """Aggregate historical outcomes into derived performance profiles.

    This is an intelligence primitive only. It produces evidence for downstream
    policy/routing owners and never authorizes or executes an action.
    """

    def __init__(self) -> None:
        self._observations: list[OutcomeObservation] = []
        self._capability_profiles: dict[str, CapabilityPerformanceProfile] = {}
        self._agent_profiles: dict[str, AgentPerformanceProfile] = {}

    def add_observation(self, observation: OutcomeObservation) -> None:
        self._observations.append(observation)
        self._update_capability_profile(observation)
        self._update_agent_profile(observation)

    def get_capability_profile(self, capability_id: str) -> CapabilityPerformanceProfile:
        return self._capability_profiles.get(
            capability_id,
            CapabilityPerformanceProfile(capability_id=capability_id),
        )

    def get_agent_profile(self, agent_id: str) -> AgentPerformanceProfile:
        return self._agent_profiles.get(
            agent_id,
            AgentPerformanceProfile(agent_id=agent_id),
        )

    def all_capability_profiles(self) -> dict[str, CapabilityPerformanceProfile]:
        return dict(self._capability_profiles)

    def all_agent_profiles(self) -> dict[str, AgentPerformanceProfile]:
        return dict(self._agent_profiles)

    def _update_capability_profile(self, observation: OutcomeObservation) -> None:
        target = observation.target_id or observation.action_type
        profile = self._capability_profiles.setdefault(
            target,
            CapabilityPerformanceProfile(capability_id=target),
        )
        profile.sample_count += 1
        profile.success_rate = self._ema(
            profile.success_rate,
            1.0 if observation.execution_status == "success" else 0.0,
        )
        profile.failure_rate = 1.0 - profile.success_rate
        profile.median_latency_ms = self._ema(
            profile.median_latency_ms,
            observation.latency_ms,
        )
        if observation.fallback_used:
            profile.retry_rate = self._ema(profile.retry_rate, 1.0)
        if observation.correction:
            profile.correction_rate = self._ema(profile.correction_rate, 1.0)
        profile.last_updated = datetime.now(timezone.utc)

    def _update_agent_profile(self, observation: OutcomeObservation) -> None:
        if observation.action_type not in ("use_agent", "use_multi_agent"):
            return
        target = observation.target_id or "unknown"
        profile = self._agent_profiles.setdefault(
            target,
            AgentPerformanceProfile(agent_id=target),
        )
        profile.sample_count += 1
        profile.success_rate = self._ema(
            profile.success_rate,
            1.0 if observation.execution_status == "success" else 0.0,
        )
        profile.median_latency_ms = self._ema(
            profile.median_latency_ms,
            observation.latency_ms,
        )
        profile.last_updated = datetime.now(timezone.utc)

    @staticmethod
    def _ema(current: float, new_value: float, alpha: float = 0.1) -> float:
        if current == 0.0 and new_value == 0.0:
            return 0.0
        if current == 0.0:
            return new_value
        return current + alpha * (new_value - current)


# Compatibility name used by the historical adaptive package.
EvidenceAggregator = PerformanceProfileAggregator


__all__ = [
    "AgentPerformanceProfile",
    "CapabilityPerformanceProfile",
    "EvidenceAggregator",
    "OutcomeObservation",
    "PerformanceProfileAggregator",
]

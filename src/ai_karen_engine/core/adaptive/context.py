"""Adaptive context builder.

Builds immutable AdaptiveContext snapshots from runtime inputs without mutating source objects.
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveContext,
    BehaviorPatternSummary,
    HistoricalEvidence,
    ResolvedPreferences,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)

logger = logging.getLogger(__name__)


class AdaptiveContextBuilder:
    """Builds AdaptiveContext from runtime inputs."""

    def __init__(
        self,
        evidence_provider: Any | None = None,
    ) -> None:
        self._evidence_provider = evidence_provider

    def build(
        self,
        request_id: str,
        correlation_id: str,
        task_signature: Any,
        user_state: UserStateSnapshot,
        resolved_preferences: ResolvedPreferences,
        behavior_patterns: BehaviorPatternSummary,
        system_capabilities: SystemCapabilitySnapshot,
        policy_version: str = "v1",
        feature_version: str = "v1",
    ) -> AdaptiveContext:
        """Build an immutable AdaptiveContext."""
        historical_evidence = self._build_historical_evidence(
            task_signature=task_signature,
            user_state=user_state,
            behavior_patterns=behavior_patterns,
        )

        return AdaptiveContext(
            request_id=request_id,
            correlation_id=correlation_id,
            task_signature=task_signature,
            user_state=user_state,
            resolved_preferences=resolved_preferences,
            behavior_patterns=behavior_patterns,
            system_capabilities=system_capabilities,
            historical_evidence=historical_evidence,
            policy_version=policy_version,
            feature_version=feature_version,
        )

    def _build_historical_evidence(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        behavior_patterns: BehaviorPatternSummary,
    ) -> HistoricalEvidence:
        evidence = HistoricalEvidence()

        if self._evidence_provider is not None:
            try:
                user_evidence = self._evidence_provider.aggregate_user_evidence(
                    user_state.user_id, user_state.tenant_id
                )
                if user_evidence:
                    evidence.user_specific_evidence = user_evidence
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to load user evidence: %s", exc)

            try:
                evidence.global_evidence = (
                    self._evidence_provider.aggregate_global_evidence()
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to load global evidence: %s", exc)

        return evidence

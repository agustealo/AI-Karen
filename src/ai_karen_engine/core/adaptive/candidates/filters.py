"""Hard constraint filters for adaptive candidates.

Filters candidates before ranking based on hard constraints:
- privacy
- local-only
- tool availability
- permissions signal
- risk
- resource limits
- user overrides
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    CandidateFilterResult,
    ResolvedPreferences,
    SystemCapabilitySnapshot,
)

logger = logging.getLogger(__name__)


class HardConstraintFilter:
    """Filters candidates against hard constraints before ranking."""

    def __init__(
        self,
        system_capabilities: SystemCapabilitySnapshot | None = None,
        resolved_preferences: ResolvedPreferences | None = None,
    ) -> None:
        self._system_capabilities = system_capabilities or SystemCapabilitySnapshot()
        self._resolved_preferences = resolved_preferences or ResolvedPreferences()

    def filter(
        self, candidates: list[dict[str, Any]], context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Apply hard constraints and return eligible candidates."""
        ctx = context or {}
        risk_level = str(ctx.get("risk_level", "low")).lower()
        local_only = bool(ctx.get("local_only", self._system_capabilities.local_only_mode))
        privacy_requirement = str(ctx.get("privacy_requirement", "none")).lower()

        filtered = []
        for candidate in candidates:
            action_type = candidate.get("action_type")
            target_id = candidate.get("target_id")
            result, reason = self._evaluate_candidate(
                action_type=action_type,
                target_id=target_id,
                risk_level=risk_level,
                local_only=local_only,
                privacy_requirement=privacy_requirement,
            )
            candidate["filter_result"] = result
            candidate["filter_reason"] = reason
            if result != CandidateFilterResult.INELIGIBLE:
                filtered.append(candidate)
            else:
                logger.debug(
                    "Filtered out candidate %s target=%s reason=%s",
                    action_type,
                    target_id,
                    reason,
                )
        return filtered

    def _evaluate_candidate(
        self,
        action_type: AdaptiveActionType | None,
        target_id: str | None,
        risk_level: str,
        local_only: bool,
        privacy_requirement: str,
    ) -> tuple[CandidateFilterResult, str]:
        if action_type is None:
            return CandidateFilterResult.INELIGIBLE, "missing_action_type"

        if privacy_requirement == "local_only" and action_type in (
            AdaptiveActionType.USE_TOOL,
            AdaptiveActionType.USE_WORKFLOW,
            AdaptiveActionType.USE_AGENT,
            AdaptiveActionType.USE_MULTI_AGENT,
        ):
            if target_id and target_id not in self._system_capabilities.available_tools:
                return (
                    CandidateFilterResult.INELIGIBLE,
                    "privacy_local_only_external_unavailable",
                )
            if local_only and target_id and "cloud" in str(target_id).lower():
                return CandidateFilterResult.INELIGIBLE, "privacy_local_only_cloud_banned"

        if action_type == AdaptiveActionType.USE_TOOL and target_id and target_id not in self._system_capabilities.available_tools:
            return CandidateFilterResult.INELIGIBLE, "tool_unavailable"

        if action_type == AdaptiveActionType.USE_AGENT and target_id and target_id not in self._system_capabilities.available_agents:
            return CandidateFilterResult.INELIGIBLE, "agent_unavailable"

        if action_type == AdaptiveActionType.USE_WORKFLOW and target_id and target_id not in self._system_capabilities.available_workflows:
            return CandidateFilterResult.INELIGIBLE, "workflow_unavailable"

        if risk_level == "critical" and action_type in (
            AdaptiveActionType.USE_AGENT,
            AdaptiveActionType.USE_MULTI_AGENT,
        ):
                return (
                    CandidateFilterResult.REQUIRES_POLICY_VALIDATION,
                    "critical_risk_requires_policy",
                )

        forbidden = set(self._resolved_preferences.forbidden_action_types)
        if action_type.value in forbidden:
            return CandidateFilterResult.INELIGIBLE, "user_forbidden_action"

        allowed = set(self._resolved_preferences.allowed_action_types)
        if allowed and action_type.value not in allowed:
            return CandidateFilterResult.REQUIRES_POLICY_VALIDATION, "not_in_allowed_list"

        return CandidateFilterResult.ELIGIBLE, "eligible"

    def update_preferences(self, preferences: ResolvedPreferences) -> None:
        self._resolved_preferences = preferences

    def update_system_capabilities(
        self, capabilities: SystemCapabilitySnapshot
    ) -> None:
        self._system_capabilities = capabilities

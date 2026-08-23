"""Action utility estimator.

Combines multiple signals into expected utility for action ranking.
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.adaptive.contracts import ScoreComponents

logger = logging.getLogger(__name__)


class ActionUtilityEstimator:
    """Estimates expected utility for adaptive action candidates."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or {
            "task_fit": 0.30,
            "user_preference_fit": 0.20,
            "historical_success": 0.25,
            "latency_penalty": -0.10,
            "risk_penalty": -0.15,
            "cost_penalty": -0.05,
            "interruption_penalty": -0.05,
            "confidence": 0.10,
        }

    def estimate(
        self,
        action_type: Any,
        target_id: str | None,
        context: dict[str, Any],
        historical_profile: dict[str, Any] | None = None,
    ) -> ScoreComponents:
        """Estimate utility components for a candidate action."""
        profile = historical_profile or {}
        task_fit = self._estimate_task_fit(action_type, target_id, context)
        user_preference_fit = self._estimate_preference_fit(action_type, target_id, context)
        historical_success = self._estimate_historical_success(action_type, target_id, profile)
        latency_penalty = self._estimate_latency_penalty(action_type, target_id, context)
        risk_penalty = self._estimate_risk_penalty(action_type, target_id, context)
        cost_penalty = self._estimate_cost_penalty(action_type, target_id, context)
        interruption_penalty = self._estimate_interruption_penalty(action_type, target_id, context)
        confidence = self._estimate_confidence(action_type, target_id, profile)

        return ScoreComponents(
            task_fit=task_fit,
            user_preference_fit=user_preference_fit,
            historical_success=historical_success,
            latency_penalty=latency_penalty,
            risk_penalty=risk_penalty,
            cost_penalty=cost_penalty,
            interruption_penalty=interruption_penalty,
            confidence=confidence,
        )

    def _estimate_task_fit(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        task_signature = context.get("task_signature")
        if task_signature is None:
            return 0.5

        complexity = getattr(task_signature, "complexity", "simple")
        ambiguity = getattr(task_signature, "ambiguity", "clear")
        tool_requirements = getattr(task_signature, "tool_requirements", []) or []
        reasoning_requirements = getattr(task_signature, "reasoning_requirements", []) or []
        collaboration_value = getattr(task_signature, "collaboration_value", 0.0)
        verification_value = getattr(task_signature, "verification_value", 0.0)

        score = 0.5
        if action_type.value == "respond_directly":
            if complexity == "simple" and ambiguity == "clear":
                score += 0.3
            if tool_requirements or reasoning_requirements:
                score -= 0.2
        elif action_type.value == "ask_clarification":
            if ambiguity in ("moderate", "ambiguous", "unknown"):
                score += 0.4
            if complexity == "simple":
                score += 0.1
        elif action_type.value == "retrieve_memory":
            memory_relevance = getattr(task_signature, "memory_relevance", 0.0) or 0.0
            score += memory_relevance * 0.5
        elif action_type.value == "use_tool":
            if target_id in tool_requirements:
                score += 0.4
            if complexity in ("moderate", "complex", "expert"):
                score += 0.1
        elif action_type.value == "use_workflow":
            if complexity in ("complex", "expert"):
                score += 0.4
            if reasoning_requirements:
                score += 0.2
        elif action_type.value == "use_agent":
            score += collaboration_value * 0.4
        elif action_type.value == "use_multi_agent":
            score += collaboration_value * 0.3
            score += verification_value * 0.3
        elif action_type.value == "suggest_action":
            score += 0.1

        return max(0.0, min(1.0, score))

    def _estimate_preference_fit(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        preferences = context.get("resolved_preferences")
        if preferences is None:
            return 0.5

        score = 0.5
        action_str = action_type.value

        if getattr(preferences, "prefers_action_over_clarification", True):
            if action_str == "ask_clarification":
                score -= 0.2
            elif action_str in ("use_tool", "use_workflow", "use_agent", "use_multi_agent"):
                score += 0.1

        if getattr(preferences, "prefers_local", False) and action_str in ("use_tool", "use_workflow") and target_id and "cloud" in str(target_id).lower():
            score -= 0.3

        if getattr(preferences, "prefers_high_verification_for_code", False) and action_str in ("use_agent", "use_multi_agent"):
                score += 0.1

        allowed = set(getattr(preferences, "allowed_action_types", []) or [])
        forbidden = set(getattr(preferences, "forbidden_action_types", []) or [])
        if allowed and action_str not in allowed:
            score -= 0.4
        if forbidden and action_str in forbidden:
            score -= 0.5

        return max(0.0, min(1.0, score))

    def _estimate_historical_success(
        self, action_type: Any, target_id: str | None, profile: dict[str, Any]
    ) -> float:
        if not profile:
            return 0.5

        action_key = action_type.value
        target_key = f"{action_key}:{target_id}" if target_id else action_key

        target_profile = profile.get(target_key)
        if target_profile is None:
            action_profile = profile.get(action_key)
            if action_profile is None:
                return 0.5
            return float(action_profile.get("success_rate", 0.5))

        return float(target_profile.get("success_rate", 0.5))

    def _estimate_latency_penalty(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        historical_evidence = context.get("historical_evidence")
        if historical_evidence is None:
            return 0.0
        if hasattr(historical_evidence, "capability_profiles"):
            capability_profiles = getattr(historical_evidence, "capability_profiles", {}) or {}
        else:
            capability_profiles = historical_evidence.get("capability_profiles", {}) if hasattr(historical_evidence, "get") else {}
        target_key = f"{target_id}" if target_id else action_type.value
        cap_profile = capability_profiles.get(target_key, {})
        median_latency = float(cap_profile.get("median_latency_ms", 0.0))
        if median_latency <= 0:
            return 0.0
        penalty = min(0.3, median_latency / 10000.0)
        return -penalty

    def _estimate_risk_penalty(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        risk_level = str(context.get("risk_level", "low")).lower()
        base_penalty = {
            "low": 0.0,
            "medium": -0.05,
            "high": -0.2,
            "critical": -0.4,
        }.get(risk_level, 0.0)

        if action_type.value in ("use_agent", "use_multi_agent", "use_workflow"):
            base_penalty -= 0.05

        return base_penalty

    def _estimate_cost_penalty(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        if action_type.value in ("use_multi_agent", "use_workflow", "use_agent"):
            return -0.05
        if action_type.value == "use_tool":
            return -0.02
        return 0.0

    def _estimate_interruption_penalty(
        self, action_type: Any, target_id: str | None, context: dict[str, Any]
    ) -> float:
        user_state = context.get("user_state")
        if user_state is None:
            return 0.0
        sensitivity = getattr(user_state, "interruption_sensitivity", 0.5)
        if action_type.value == "ask_clarification":
            return -sensitivity * 0.2
        if action_type.value in ("use_multi_agent", "use_workflow"):
            return -sensitivity * 0.1
        return 0.0

    def _estimate_confidence(
        self, action_type: Any, target_id: str | None, profile: dict[str, Any]
    ) -> float:
        if not profile:
            return 0.5

        action_key = action_type.value
        target_key = f"{action_key}:{target_id}" if target_id else action_key

        target_profile = profile.get(target_key)
        if target_profile is None:
            action_profile = profile.get(action_key)
            if action_profile is None:
                return 0.5
            sample_count = int(action_profile.get("sample_count", 0))
            return min(1.0, 0.5 + sample_count / 100.0)

        sample_count = int(target_profile.get("sample_count", 0))
        confidence_interval = float(target_profile.get("confidence_interval", 0.0))
        base = max(0.0, 1.0 - confidence_interval)
        return min(1.0, base + sample_count / 200.0)

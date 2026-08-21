"""
Runtime Policy — Global execution authority outside LangGraph.

This module owns the global runtime-level provider/tool/response restrictions
that previously lived under ``langgraph_orchestrator/``. LangGraph is a
workflow executor; it must not own global degraded-mode transitions, provider
selection, or intent routing.

Public surface:
- RuntimeLevel
- PolicyCheckResult
- RuntimePolicyConfig
- RuntimePolicyEnforcer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeLevel(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    SAFE = "SAFE"
    EMERGENCY = "EMERGENCY"


class PolicyCheckResult:
    def __init__(self, allowed: bool, reason: str, severity: str = "info"):
        self.allowed = allowed
        self.reason = reason
        self.severity = severity


@dataclass
class RuntimePolicyConfig:
    default_level: RuntimeLevel = RuntimeLevel.FULL
    enable_degraded_mode: bool = True
    enable_routing_restrictions: bool = True
    enable_execution_constraints: bool = True
    enable_safety_overrides: bool = True


class RuntimePolicyEnforcer:
    """Enforces runtime policies across ALL execution paths (direct and graph)."""

    def __init__(self, config: Optional[RuntimePolicyConfig] = None):
        self.config = config or RuntimePolicyConfig()
        self.level_transitions = {
            RuntimeLevel.FULL: [RuntimeLevel.REDUCED],
            RuntimeLevel.REDUCED: [RuntimeLevel.SAFE, RuntimeLevel.FULL],
            RuntimeLevel.SAFE: [RuntimeLevel.EMERGENCY, RuntimeLevel.REDUCED],
            RuntimeLevel.EMERGENCY: [RuntimeLevel.SAFE],
        }

    async def check_routing_policy(
        self, state: Dict[str, Any], provider_selection: Dict[str, Any]
    ) -> PolicyCheckResult:
        if not self.config.enable_routing_restrictions:
            return PolicyCheckResult(True, "Routing restrictions disabled")

        current_level = self._get_runtime_level(state)
        provider = provider_selection.get("provider")
        model = provider_selection.get("model")

        if current_level == RuntimeLevel.EMERGENCY:
            if provider not in ["fallback", "local"]:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not allowed in {current_level} mode",
                    "critical",
                )
        elif current_level == RuntimeLevel.SAFE:
            trusted_providers = ["openai", "anthropic", "local"]
            if provider not in trusted_providers:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not trusted in {current_level} mode",
                    "high",
                )
        elif current_level == RuntimeLevel.REDUCED:
            complex_models = ["gpt-4", "claude-3", "gemini-pro"]
            if any(m in complex_models for m in [model] if model):
                return PolicyCheckResult(
                    False,
                    f"Complex models not allowed in {current_level} mode",
                    "medium",
                )

        return PolicyCheckResult(True, "Routing policy check passed")

    async def check_execution_policy(
        self, state: Dict[str, Any], execution_plan: Dict[str, Any]
    ) -> PolicyCheckResult:
        if not self.config.enable_execution_constraints:
            return PolicyCheckResult(True, "Execution constraints disabled")

        current_level = self._get_runtime_level(state)
        intent = execution_plan.get("intent", "general_chat")

        if current_level == RuntimeLevel.EMERGENCY:
            allowed_intents = ["general_chat", "information_retrieval", "basic_search"]
            if intent not in allowed_intents:
                return PolicyCheckResult(
                    False,
                    f"Intent '{intent}' not allowed in {current_level} mode",
                    "critical",
                )
        elif current_level == RuntimeLevel.SAFE:
            high_risk_intents = ["code_generation", "file_access", "system_command"]
            if intent in high_risk_intents:
                return PolicyCheckResult(
                    False,
                    f"High-risk intent '{intent}' not allowed in {current_level} mode",
                    "high",
                )

        tools_required = execution_plan.get("tools_required", [])
        if tools_required:
            tool_check = await self._check_tool_availability(tools_required, current_level)
            if not tool_check.allowed:
                return tool_check

        return PolicyCheckResult(True, "Execution policy check passed")

    async def check_response_policy(
        self, state: Dict[str, Any], response_content: str
    ) -> PolicyCheckResult:
        if not self.config.enable_safety_overrides:
            return PolicyCheckResult(True, "Safety overrides disabled")

        current_level = self._get_runtime_level(state)

        if current_level == RuntimeLevel.EMERGENCY:
            if len(response_content) > 500:
                return PolicyCheckResult(
                    False, "Response too long for emergency mode", "critical"
                )
        elif current_level == RuntimeLevel.SAFE:
            harmful_keywords = ["delete", "remove", "disable", "format", "reset"]
            if any(keyword in response_content.lower() for keyword in harmful_keywords):
                return PolicyCheckResult(
                    False, "Response contains potentially harmful content", "high"
                )

        return PolicyCheckResult(True, "Response policy check passed")

    async def enforce_runtime_level_transition(
        self, current_level: RuntimeLevel, target_level: RuntimeLevel
    ) -> PolicyCheckResult:
        if target_level not in self.level_transitions.get(current_level, []):
            return PolicyCheckResult(
                False,
                f"Cannot transition from {current_level} to {target_level}",
                "critical",
            )
        return PolicyCheckResult(True, "Runtime level transition allowed")

    def _get_runtime_level(self, state: Dict[str, Any]) -> RuntimeLevel:
        level_str = state.get("runtime_level", self.config.default_level.value)
        try:
            return RuntimeLevel(level_str)
        except ValueError:
            logger.warning(f"Invalid runtime level '{level_str}', using default")
            return self.config.default_level

    async def _check_tool_availability(
        self, tools: List[str], runtime_level: RuntimeLevel
    ) -> PolicyCheckResult:
        tool_restrictions = {
            RuntimeLevel.FULL: [],
            RuntimeLevel.REDUCED: ["file_access", "system_command"],
            RuntimeLevel.SAFE: ["file_access", "system_command", "code_generation"],
            RuntimeLevel.EMERGENCY: [
                "file_access",
                "system_command",
                "code_generation",
                "network_access",
            ],
        }

        restricted_tools = tool_restrictions.get(runtime_level, [])
        for tool in tools:
            if tool in restricted_tools:
                return PolicyCheckResult(
                    False,
                    f"Tool '{tool}' not available in {runtime_level} mode",
                    "high",
                )
        return PolicyCheckResult(True, "Tool availability check passed")

    def apply_runtime_constraints(self, state: Dict[str, Any]) -> Dict[str, Any]:
        current_level = self._get_runtime_level(state)
        state["runtime_constraints"] = {
            "level": current_level.value,
            "applied_at": state.get("timestamp"),
            "effective_immediately": True,
        }

        if current_level == RuntimeLevel.EMERGENCY:
            state["streaming_enabled"] = False
            state["max_response_length"] = 500
            state["enable_tool_execution"] = False
        elif current_level == RuntimeLevel.SAFE:
            state["streaming_enabled"] = False
            state["max_response_length"] = 2000
            state["enable_tool_execution"] = True
            state["allowed_tool_types"] = ["basic_search", "information_retrieval"]
        elif current_level == RuntimeLevel.REDUCED:
            state["streaming_enabled"] = True
            state["max_response_length"] = 5000
            state["enable_tool_execution"] = True
            state["allowed_tool_types"] = [
                "basic_search",
                "information_retrieval",
                "text_analysis",
            ]
        else:
            state["streaming_enabled"] = True
            state["max_response_length"] = 100000
            state["enable_tool_execution"] = True
            state["allowed_tool_types"] = ["all"]

        return state

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
- PolicyEvaluationRequest
- PolicyDecision
- PolicyReasonCode
- PolicyResourceScope
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeLevel(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    SAFE = "SAFE"
    EMERGENCY = "EMERGENCY"


class PolicyReasonCode(str, Enum):
    ALLOWED = "allowed"
    MISSING_IDENTITY = "missing_identity"
    CAPABILITY_CONFLICT = "capability_conflict"
    INSUFFICIENT_PERMISSION = "insufficient_permission"
    TOOL_RISK_DENIED = "tool_risk_denied"
    RUNTIME_LEVEL_DENIED = "runtime_level_denied"
    RESOURCE_SCOPE_DENIED = "resource_scope_denied"
    POLICY_CHECK_PASSED = "policy_check_passed"


@dataclass
class PolicyResourceScope:
    """Trusted resource scope for policy decisions."""

    allowed_paths: List[str] = field(default_factory=list)
    forbidden_paths: List[str] = field(default_factory=list)
    max_file_size_mb: int = 10
    allowed_networks: List[str] = field(default_factory=lambda: ["internal"])
    forbidden_networks: List[str] = field(default_factory=list)


@dataclass
class PolicyEvaluationRequest:
    """Typed request for policy evaluation."""

    user_id: str
    tenant_id: str
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    action: str = "general_assist"
    resource: Optional[str] = None
    requested_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    risk_signals: Dict[str, Any] = field(default_factory=dict)
    runtime_level: RuntimeLevel = RuntimeLevel.FULL
    extension_id: Optional[str] = None
    tool_id: Optional[str] = None
    provider_constraints: Dict[str, Any] = field(default_factory=dict)
    environment: str = "production"
    resource_scope: Optional[PolicyResourceScope] = None


@dataclass
class PolicyDecision:
    """Typed policy decision."""

    decision_id: str
    policy_version: str
    allowed: bool
    reason_codes: List[PolicyReasonCode] = field(default_factory=list)
    allowed_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    requires_human_gate: bool = False
    runtime_constraints: Dict[str, Any] = field(default_factory=dict)
    resource_scope: Optional[PolicyResourceScope] = None


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

    async def evaluate(self, request: PolicyEvaluationRequest) -> PolicyDecision:
        """Evaluate a typed policy request and return a typed decision."""
        decision_id = f"policy-{request.tenant_id}-{request.user_id}-{int(time.time() * 1000)}"
        policy_version = "v1"

        if not request.user_id or not request.tenant_id:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.MISSING_IDENTITY],
                forbidden_capabilities=["all"],
            )

        forbidden = set(request.forbidden_capabilities)
        for cap in request.requested_capabilities:
            if cap in forbidden:
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.CAPABILITY_CONFLICT],
                    forbidden_capabilities=list(forbidden),
                )

        risk_score = float(request.risk_signals.get("score", 0.0) or 0.0)
        risk_categories = request.risk_signals.get("categories", []) or []
        if "credential_access" in risk_categories or "production_impact" in risk_categories:
            risk_score = max(risk_score, 0.7)
        if "destructive_action" in risk_categories:
            risk_score = max(risk_score, 0.5)

        if risk_score >= 0.8 and "admin" not in request.permissions:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                forbidden_capabilities=["admin", "write", "delete"],
                requires_human_gate=True,
            )

        if request.tool_id and "admin" not in request.permissions and risk_score >= 0.5:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.TOOL_RISK_DENIED],
                forbidden_capabilities=list(forbidden | {"admin", "write", "delete"}),
            )

        runtime_constraints = self._build_runtime_constraints(request.runtime_level)

        return PolicyDecision(
            decision_id=decision_id,
            policy_version=policy_version,
            allowed=True,
            reason_codes=[PolicyReasonCode.POLICY_CHECK_PASSED],
            allowed_capabilities=list(request.requested_capabilities),
            forbidden_capabilities=list(forbidden),
            runtime_constraints=runtime_constraints,
            resource_scope=request.resource_scope,
        )

    async def check_routing_policy(
        self, state: Dict[str, Any], provider_selection: Dict[str, Any]
    ) -> PolicyCheckResult:
        if not self.config.enable_routing_restrictions:
            return PolicyCheckResult(True, "Routing restrictions disabled")

        current_level = self._get_runtime_level(state)
        provider = provider_selection.get("provider")
        model = provider_selection.get("model")
        provider_constraints = state.get("provider_constraints", {})

        if current_level == RuntimeLevel.EMERGENCY:
            allowed_providers = provider_constraints.get("emergency_allowed_providers", ["local"])
            if provider not in allowed_providers:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not allowed in {current_level} mode",
                    "critical",
                )
        elif current_level == RuntimeLevel.SAFE:
            trusted_providers = provider_constraints.get("safe_trusted_providers", ["local"])
            if provider not in trusted_providers:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not trusted in {current_level} mode",
                    "high",
                )
        elif current_level == RuntimeLevel.REDUCED:
            complex_models = provider_constraints.get("reduced_complex_models", [])
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
        requested_capabilities = execution_plan.get("requested_capabilities", [])
        forbidden_capabilities = execution_plan.get("forbidden_capabilities", [])

        forbidden = set(forbidden_capabilities)
        for cap in requested_capabilities:
            if cap in forbidden:
                return PolicyCheckResult(
                    False,
                    f"Required capability '{cap}' is forbidden",
                    "high",
                )

        restricted_capabilities = self._resolve_restricted_capabilities(current_level, state)
        for cap in requested_capabilities:
            if cap in restricted_capabilities:
                return PolicyCheckResult(
                    False,
                    f"Capability '{cap}' not available in {current_level} mode",
                    "high",
                )

        tools_required = execution_plan.get("tool_requirements", []) or execution_plan.get("tools_required", [])
        if tools_required:
            tool_check = await self._check_tool_availability(tools_required, current_level, state)
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
        self,
        tools: List[str],
        runtime_level: RuntimeLevel,
        state: Dict[str, Any],
    ) -> PolicyCheckResult:
        tool_restrictions = {
            RuntimeLevel.FULL: [],
            RuntimeLevel.REDUCED: ["file_access", "system_command"],
            RuntimeLevel.SAFE: ["file_access", "system_command", "code_execution"],
            RuntimeLevel.EMERGENCY: [
                "file_access",
                "system_command",
                "code_execution",
                "network_access",
            ],
        }

        state_restrictions = state.get("runtime_constraints", {}).get("allowed_tool_types", [])
        if state_restrictions and "all" not in state_restrictions:
            combined_restrictions = set(tool_restrictions.get(runtime_level, [])) | {
                tool for tool in ["file_access", "system_command", "code_execution", "network_access", "web_search"]
                if tool not in state_restrictions
            }
        else:
            combined_restrictions = set(tool_restrictions.get(runtime_level, []))

        for tool in tools:
            if tool in combined_restrictions:
                return PolicyCheckResult(
                    False,
                    f"Tool '{tool}' not available in {runtime_level.value} mode",
                    "high",
                )
        return PolicyCheckResult(True, "Tool availability check passed")

    def _resolve_restricted_capabilities(self, runtime_level: RuntimeLevel, state: Dict[str, Any]) -> List[str]:
        capability_restrictions = {
            RuntimeLevel.FULL: [],
            RuntimeLevel.REDUCED: ["admin", "delete", "write"],
            RuntimeLevel.SAFE: ["admin", "delete", "write", "network_access"],
            RuntimeLevel.EMERGENCY: ["admin", "delete", "write", "network_access", "code_execution"],
        }

        state_restrictions = state.get("runtime_constraints", {}).get("allowed_capabilities", [])
        if state_restrictions:
            return [cap for cap in capability_restrictions.get(runtime_level, []) if cap not in state_restrictions]
        return capability_restrictions.get(runtime_level, [])

    def _build_runtime_constraints(self, runtime_level: RuntimeLevel) -> Dict[str, Any]:
        constraints = {
            RuntimeLevel.FULL: {
                "streaming_enabled": True,
                "max_response_length": 100000,
                "enable_tool_execution": True,
                "allowed_tool_types": ["all"],
            },
            RuntimeLevel.REDUCED: {
                "streaming_enabled": True,
                "max_response_length": 5000,
                "enable_tool_execution": True,
                "allowed_tool_types": [
                    "basic_search",
                    "information_retrieval",
                    "text_analysis",
                ],
            },
            RuntimeLevel.SAFE: {
                "streaming_enabled": False,
                "max_response_length": 2000,
                "enable_tool_execution": True,
                "allowed_tool_types": ["basic_search", "information_retrieval"],
            },
            RuntimeLevel.EMERGENCY: {
                "streaming_enabled": False,
                "max_response_length": 500,
                "enable_tool_execution": False,
                "allowed_tool_types": [],
            },
        }

        return constraints.get(runtime_level, constraints[RuntimeLevel.FULL])

    def apply_runtime_constraints(self, state: Dict[str, Any]) -> Dict[str, Any]:
        current_level = self._get_runtime_level(state)
        state["runtime_constraints"] = self._build_runtime_constraints(current_level)
        state["runtime_constraints"]["level"] = current_level.value
        state["runtime_constraints"]["applied_at"] = state.get("timestamp")
        state["runtime_constraints"]["effective_immediately"] = True
        return state

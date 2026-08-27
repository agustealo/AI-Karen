from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.intelligence import get_intelligence_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RiskLevel,
    RuntimeExecutionMode,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)

logger = logging.getLogger(__name__)

_FORCE_GRAPH_ENV = "KARI_RUNTIME_FORCE_GRAPH"
_SOFT_REASONING_MAX_MODEL_CALLS = 30


class CortexExecutionDecider:
    """Canonical live CORTEX adapter for ChatRuntime.

    CORTEX decides what kind of execution a request needs. IntelligenceRuntime
    supplies cognitive signals. RuntimePolicy is the sole authorization owner.
    This component never executes providers, tools, plugins, memory, or graphs.

    ``core.cortex.dispatch`` remains a compatibility surface and must not become
    a second canonical decision path.
    """

    def __init__(self, *, force_graph: Optional[bool] = None):
        self._force_graph = (
            force_graph
            if force_graph is not None
            else os.environ.get(_FORCE_GRAPH_ENV, "false").lower()
            in ("1", "true", "yes")
        )
        self._intelligence = get_intelligence_runtime()
        self._policy_enforcer = RuntimePolicyEnforcer()

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        meta = request.metadata or {}
        ctx = request.context
        reason_codes: List[str] = []

        user_id = ctx.user_id
        tenant_id = ctx.tenant_id
        session_id = getattr(ctx, "session_id", None)
        roles = list(ctx.roles or [])
        permissions = list(ctx.permissions or [])

        user_content = self._extract_user_content(request.messages)
        analysis = await self._analyze_request(user_content, ctx)

        explicit_graph = bool(meta.get("graph_required") or meta.get("force_graph"))
        if explicit_graph:
            reason_codes.append("explicit_graph_request")

        topology_triggers = self._evaluate_topology_triggers(analysis)
        graph_required = explicit_graph or bool(topology_triggers)
        reason_codes.extend(topology_triggers)

        tool_requirements = analysis.get("tool_requirements", []) or list(
            meta.get("tool_requirements") or []
        )
        plugin_candidates = analysis.get("plugin_candidates", []) or list(
            meta.get("plugin_candidates") or []
        )
        required_capabilities = analysis.get("required_capabilities", []) or list(
            meta.get("required_capabilities") or []
        )
        denied_capabilities = analysis.get("forbidden_capabilities", []) or list(
            meta.get("forbidden_capabilities") or []
        )
        policy_constraints = dict(meta.get("policy_constraints") or {})

        if meta.get("agent_delegation"):
            analysis["agent_delegation"] = True
        if meta.get("workflow_required"):
            analysis["workflow_required"] = True

        if tool_requirements or plugin_candidates:
            graph_required = True
            reason_codes.append("tool_or_plugin_requirements")
        if analysis.get("workflow_required") or analysis.get("agent_delegation"):
            graph_required = True
            reason_codes.append("workflow_capability")

        risk_level = self._assess_risk_level(analysis)
        requires_human_gate = bool(analysis.get("requires_human_gate", False)) or risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        requires_resumability = bool(analysis.get("requires_resumability", False))
        requires_parallel_execution = bool(
            analysis.get("requires_parallel_execution", False)
        )
        requires_agent_delegation = bool(analysis.get("agent_delegation", False))

        if requires_human_gate:
            graph_required = True
            reason_codes.append("human_gate_required")
        if requires_agent_delegation:
            graph_required = True
            reason_codes.append("agent_delegation_required")

        memory_recall_required = bool(
            analysis.get("memory_recall_required", False)
        ) or bool(meta.get("memory_recall_required", False))
        memory_write_requested = bool(
            analysis.get("memory_write_requested", False)
            or meta.get("memory_write_requested", False)
        )
        if analysis.get("memory_write_denied", False):
            memory_write_requested = False
        memory_scope = str(
            analysis.get("memory_scope", meta.get("memory_scope", "session"))
        )
        memory_top_k = int(
            analysis.get("memory_top_k", meta.get("memory_top_k", 10))
        )
        memory_classes = list(analysis.get("memory_classes", []))

        max_steps = int(meta.get("max_steps", analysis.get("max_steps", 10)))
        time_budget_ms = int(
            meta.get("time_budget_ms", analysis.get("time_budget_ms", 30000))
        )
        token_budget = int(
            meta.get("token_budget", analysis.get("token_budget", 4096))
        )
        reasoning_depth = str(
            meta.get("reasoning_depth", analysis.get("reasoning_depth", "standard"))
        )
        reasoning_modes = self._normalize_reasoning_modes(
            analysis.get("reasoning_modes") or meta.get("reasoning_modes") or []
        )
        if (reasoning_depth == "deep" or analysis.get("reasoning_required")) and not reasoning_modes:
            reasoning_modes = ["causal", "verify", "refine", "metacognition"]

        inferred_model_calls = int(analysis.get("max_model_calls", max_steps))
        if "soft_exploration" in reasoning_modes:
            inferred_model_calls = max(
                inferred_model_calls,
                _SOFT_REASONING_MAX_MODEL_CALLS,
            )
        max_model_calls = int(meta.get("max_model_calls", inferred_model_calls))

        requested_capabilities = list(required_capabilities)
        if memory_write_requested and "memory.write" not in requested_capabilities:
            requested_capabilities.append("memory.write")

        policy_evaluation = PolicyEvaluationRequest(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            correlation_id=getattr(request, "correlation_id", None),
            roles=roles,
            permissions=permissions,
            action="general_assist",
            requested_capabilities=requested_capabilities,
            forbidden_capabilities=denied_capabilities,
            risk_signals=analysis.get("risk_signals", {}),
            runtime_level=self._risk_level_to_runtime_level(risk_level),
            tool_id=tool_requirements[0] if tool_requirements else None,
            environment="production",
            execution_topology={
                "tool_requirements": tool_requirements,
                "plugin_candidates": plugin_candidates,
                "requires_human_gate": requires_human_gate,
                "reasoning_modes": reasoning_modes,
                "max_model_calls": max_model_calls,
            },
        )
        policy_decision = await self._policy_enforcer.evaluate(policy_evaluation)

        if not policy_decision.allowed:
            return ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DEGRADED,
                graph_required=False,
                intent=analysis.get("intent", "general_assist"),
                intent_confidence=float(analysis.get("intent_confidence", 0.0)),
                risk_level=RiskLevel.CRITICAL,
                reasoning_depth=reasoning_depth,
                reasoning_modes=[],
                memory_recall_required=False,
                memory_write_allowed=False,
                memory_scope=memory_scope,
                memory_top_k=memory_top_k,
                memory_classes=memory_classes,
                tool_requirements=[],
                plugin_candidates=[],
                required_capabilities=[],
                forbidden_capabilities=list(policy_decision.denied_capabilities),
                requires_human_gate=True,
                max_steps=0,
                max_model_calls=0,
                time_budget_ms=0,
                token_budget=0,
                workflow_id=analysis.get("workflow_id"),
                workflow_version="v1",
                policy_decision_id=policy_decision.decision_id,
                policy_version=policy_decision.policy_version,
                policy_reason_codes=[
                    code.value for code in policy_decision.reason_codes
                ],
                reason_codes=["policy_denied", *reason_codes],
                policy_constraints={
                    "denial_reason": (
                        policy_decision.reason_codes[0].value
                        if policy_decision.reason_codes
                        else "policy_denied"
                    )
                },
            )

        required_capabilities = list(policy_decision.allowed_capabilities)
        denied_capabilities = list(
            set(denied_capabilities) | set(policy_decision.denied_capabilities)
        )
        memory_write_allowed = (
            memory_write_requested and "memory.write" in required_capabilities
        )

        if self._force_graph:
            graph_required = True
            reason_codes.append("force_graph_override")

        execution_mode = (
            RuntimeExecutionMode.GRAPH
            if graph_required
            else RuntimeExecutionMode.DIRECT
        )

        topology = ExecutionTopology.DIRECT
        if requires_agent_delegation:
            topology = ExecutionTopology.MULTI_AGENT
        elif reasoning_modes or reasoning_depth == "deep" or analysis.get("reasoning_required"):
            topology = ExecutionTopology.REASONING
        elif graph_required:
            topology = ExecutionTopology.WORKFLOW

        return ExecutionDecision(
            execution_mode=execution_mode,
            graph_required=graph_required,
            topology=topology,
            intent=analysis.get("intent", "general_assist"),
            intent_confidence=float(analysis.get("intent_confidence", 0.0)),
            risk_level=risk_level,
            reasoning_depth=reasoning_depth,
            reasoning_modes=reasoning_modes,
            memory_recall_required=memory_recall_required,
            memory_write_allowed=memory_write_allowed,
            memory_scope=memory_scope,
            memory_top_k=memory_top_k,
            memory_classes=memory_classes,
            tool_requirements=tool_requirements,
            plugin_candidates=plugin_candidates,
            required_capabilities=required_capabilities,
            forbidden_capabilities=denied_capabilities,
            requires_human_gate=requires_human_gate,
            requires_resumability=requires_resumability,
            requires_parallel_execution=requires_parallel_execution,
            requires_agent_delegation=requires_agent_delegation,
            max_steps=max_steps,
            max_model_calls=max_model_calls,
            time_budget_ms=time_budget_ms,
            token_budget=token_budget,
            workflow_id=analysis.get("workflow_id"),
            workflow_version="v1",
            policy_decision_id=policy_decision.decision_id,
            policy_version=policy_decision.policy_version,
            policy_reason_codes=[code.value for code in policy_decision.reason_codes],
            reason_codes=reason_codes,
            policy_constraints={
                **policy_constraints,
                "memory_write_requested": memory_write_requested,
                "memory_write_authorized": memory_write_allowed,
                "max_model_calls": max_model_calls,
            },
        )

    @staticmethod
    def _normalize_reasoning_modes(values: Any) -> List[str]:
        if isinstance(values, str):
            values = [values]
        normalized: List[str] = []
        seen: set[str] = set()
        for raw in values or []:
            value = str(raw).strip().lower()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return normalized

    def _risk_level_to_runtime_level(self, risk_level: RiskLevel) -> Any:
        from ai_karen_engine.core.runtime.policy import RuntimeLevel

        mapping = {
            RiskLevel.LOW: RuntimeLevel.FULL,
            RiskLevel.MEDIUM: RuntimeLevel.REDUCED,
            RiskLevel.HIGH: RuntimeLevel.SAFE,
            RiskLevel.CRITICAL: RuntimeLevel.EMERGENCY,
        }
        return mapping.get(risk_level, RuntimeLevel.FULL)

    def _extract_user_content(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            role = str(msg.get("role", "")).lower()
            if role == "user":
                return str(msg.get("content", ""))
        return str(messages[-1].get("content", ""))

    async def _analyze_request(
        self, text: str, ctx: ChatExecutionContext
    ) -> Dict[str, Any]:
        if not text or not text.strip():
            return self._default_analysis()

        try:
            analysis = await self._intelligence.analyze(
                text,
                {"user_id": ctx.user_id, "session_id": ctx.session_id},
            )
            intent_value = analysis.intent or "general_assist"
            confidence = analysis.intent_confidence or 0.0

            topology = self._infer_topology_from_analysis(analysis)
            capabilities = self._infer_capabilities_from_analysis(analysis)
            memory_policy = self._infer_memory_policy_from_analysis(analysis)
            workflow = self._infer_workflow_from_analysis(analysis)
            risk_level = self._assess_risk_level(analysis)
            reasoning_modes = self._normalize_reasoning_modes(
                getattr(analysis, "reasoning_modes", []) or []
            )

            lower_text = text.lower()
            heuristic_tools: List[str] = []
            if any(
                k in lower_text
                for k in ["debug", "error", "traceback", "exception", "bug"]
            ):
                heuristic_tools.append("code_execution")
            if any(
                k in lower_text
                for k in ["repository", "repo", "codebase", "folder", "directory"]
            ):
                heuristic_tools.append("filesystem_operation")
            for tool in heuristic_tools:
                if tool not in topology.get("tool_requirements", []):
                    topology.setdefault("tool_requirements", []).append(tool)

            return {
                "intent": intent_value,
                "intent_confidence": confidence,
                "task_complexity": getattr(analysis, "task_complexity", "simple"),
                "memory_relevance": getattr(analysis, "memory_relevance", 0.0),
                "topology_signals": getattr(analysis, "topology_signals", {}),
                "risk_signals": getattr(analysis, "risk_signals", {}),
                "capability_hints": getattr(analysis, "capability_hints", {}),
                "tool_requirements": topology.get("tool_requirements", []),
                "plugin_candidates": topology.get("plugin_candidates", []),
                "required_capabilities": capabilities.get("required", []),
                "forbidden_capabilities": capabilities.get("forbidden", []),
                "reasoning_modes": reasoning_modes,
                "reasoning_required": bool(reasoning_modes)
                or topology.get("reasoning_depth") == "deep",
                "memory_recall_required": memory_policy.get("recall_required", False),
                "memory_write_requested": memory_policy.get("write_requested", False),
                "memory_write_denied": memory_policy.get("write_denied", False),
                "memory_scope": memory_policy.get("scope", "session"),
                "memory_top_k": memory_policy.get("top_k", 10),
                "memory_classes": memory_policy.get("classes", []),
                "requires_human_gate": topology.get("requires_human_gate", False)
                or risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
                "requires_resumability": topology.get("requires_resumability", False),
                "requires_parallel_execution": topology.get(
                    "requires_parallel_execution", False
                ),
                "agent_delegation": topology.get("agent_delegation", False),
                "max_steps": topology.get("max_steps", 10),
                "max_model_calls": topology.get(
                    "max_model_calls", topology.get("max_steps", 10)
                ),
                "time_budget_ms": topology.get("time_budget_ms", 30000),
                "token_budget": topology.get("token_budget", 4096),
                "reasoning_depth": topology.get("reasoning_depth", "standard"),
                "workflow_required": workflow.get("required", False),
                "workflow_id": workflow.get("workflow_id"),
                "risk_level": (
                    risk_level.value
                    if isinstance(risk_level, RiskLevel)
                    else str(risk_level)
                ),
                "risk_score": (getattr(analysis, "risk_signals", {}) or {}).get(
                    "score", 0.0
                ),
                "risk_categories": (
                    getattr(analysis, "risk_signals", {}) or {}
                ).get("categories", []),
            }
        except Exception as exc:
            logger.warning("CORTEX analysis failed, using safe defaults: %s", exc)
            return self._default_analysis()

    def _default_analysis(self) -> Dict[str, Any]:
        return {
            "intent": "general_assist",
            "intent_confidence": 0.0,
            "task_complexity": "simple",
            "memory_relevance": 0.0,
            "topology_signals": {},
            "risk_signals": {"categories": [], "score": 0.0},
            "capability_hints": {},
            "tool_requirements": [],
            "plugin_candidates": [],
            "required_capabilities": [],
            "forbidden_capabilities": [],
            "reasoning_modes": [],
            "reasoning_required": False,
            "memory_recall_required": False,
            "memory_write_requested": False,
            "memory_write_denied": False,
            "memory_scope": "session",
            "memory_top_k": 10,
            "memory_classes": [],
            "requires_human_gate": False,
            "requires_resumability": False,
            "requires_parallel_execution": False,
            "agent_delegation": False,
            "max_steps": 10,
            "max_model_calls": 10,
            "time_budget_ms": 30000,
            "token_budget": 4096,
            "reasoning_depth": "standard",
            "workflow_required": False,
            "workflow_id": None,
            "risk_level": RiskLevel.LOW.value,
            "risk_score": 0.0,
            "risk_categories": [],
        }

    def _infer_topology_from_analysis(self, analysis: Any) -> Dict[str, Any]:
        topology: Dict[str, Any] = {
            "tool_requirements": [],
            "plugin_candidates": [],
            "requires_human_gate": False,
            "requires_resumability": False,
            "requires_parallel_execution": False,
            "agent_delegation": False,
            "max_steps": 10,
            "max_model_calls": 10,
            "time_budget_ms": 30000,
            "token_budget": 4096,
            "reasoning_depth": "standard",
            "risk_signals": [],
            "filesystem_write": False,
            "network_access": False,
            "system_command": False,
        }

        topology_signals = getattr(analysis, "topology_signals", {}) or {}
        capability_hints = getattr(analysis, "capability_hints", {}) or {}
        task_complexity = getattr(analysis, "task_complexity", "simple")

        if topology_signals.get("external_lookup"):
            topology["tool_requirements"].append("search")
        if topology_signals.get("code_execution"):
            topology["tool_requirements"].append("code_execution")
        if topology_signals.get("filesystem_operation"):
            topology["tool_requirements"].append("filesystem_operation")
        if capability_hints.get("web_search"):
            topology["tool_requirements"].append("web_search")

        if topology_signals.get("multiple_actions") or topology_signals.get(
            "dependency_chain"
        ):
            topology["requires_resumability"] = True
            topology["reasoning_depth"] = "deep"

        if topology_signals.get("parallelizable"):
            topology["requires_parallel_execution"] = True

        if task_complexity == "complex":
            topology["requires_resumability"] = True
            topology["reasoning_depth"] = "deep"
            topology["max_steps"] = max(topology["max_steps"], 20)
            topology["max_model_calls"] = max(topology["max_model_calls"], 20)

        return topology

    def _infer_capabilities_from_analysis(self, analysis: Any) -> Dict[str, Any]:
        capabilities: Dict[str, Any] = {"required": [], "forbidden": []}
        capability_hints = getattr(analysis, "capability_hints", {}) or {}
        risk_signals = getattr(analysis, "risk_signals", {}) or {}

        if capability_hints.get("web_search"):
            capabilities["required"].append("web")
        if capability_hints.get("code_execution"):
            capabilities["required"].append("code_execution")
        if capability_hints.get("filesystem_read"):
            capabilities["required"].append("filesystem_read")
        if capability_hints.get("filesystem_write"):
            capabilities["required"].append("filesystem_write")
        if capability_hints.get("structured_output"):
            capabilities["required"].append("structured_output")
        if capability_hints.get("deep_reasoning"):
            capabilities["required"].append("reasoning")

        risk_categories = risk_signals.get("categories", [])
        if "credential_access" in risk_categories or "production_impact" in risk_categories:
            capabilities["forbidden"].append("admin")
        if "destructive_action" in risk_categories:
            capabilities["forbidden"].append("delete")
        return capabilities

    def _infer_memory_policy_from_analysis(self, analysis: Any) -> Dict[str, Any]:
        policy: Dict[str, Any] = {
            "recall_required": False,
            "write_requested": False,
            "write_denied": False,
            "scope": "session",
            "top_k": 10,
            "classes": [],
        }
        memory_relevance = getattr(analysis, "memory_relevance", 0.0) or 0.0
        task_complexity = getattr(analysis, "task_complexity", "simple")
        if memory_relevance >= 0.5:
            policy["recall_required"] = True
            policy["scope"] = "user"
            policy["top_k"] = 15
        if task_complexity == "complex":
            policy["top_k"] = max(policy["top_k"], 20)
        return policy

    def _infer_workflow_from_analysis(self, analysis: Any) -> Dict[str, Any]:
        workflow: Dict[str, Any] = {"required": False, "workflow_id": None}
        topology_signals = getattr(analysis, "topology_signals", {}) or {}
        capability_hints = getattr(analysis, "capability_hints", {}) or {}
        task_complexity = getattr(analysis, "task_complexity", "simple")
        if topology_signals.get("dependency_chain") or task_complexity == "complex":
            workflow["required"] = True
            workflow["workflow_id"] = "multi_step_pipeline"
        if capability_hints.get("code_execution") and topology_signals.get(
            "external_lookup"
        ):
            workflow["required"] = True
            workflow["workflow_id"] = "research_and_code"
        return workflow

    def _evaluate_topology_triggers(self, analysis: Dict[str, Any]) -> List[str]:
        triggers: List[str] = []
        if analysis.get("requires_human_gate"):
            triggers.append("human_gate_required")
        if analysis.get("requires_resumability"):
            triggers.append("resumability")
        if analysis.get("requires_parallel_execution"):
            triggers.append("parallel_execution")
        if analysis.get("agent_delegation"):
            triggers.append("agent_delegation")
        if analysis.get("workflow_required"):
            triggers.append("workflow_required")
        return triggers

    def _assess_risk_level(self, analysis: Any) -> RiskLevel:
        if hasattr(analysis, "get"):
            risk_signals = dict((analysis.get("risk_signals", {}) or {}))
        else:
            risk_signals = dict(getattr(analysis, "risk_signals", {}) or {})
        risk_score = float(risk_signals.get("score", 0.0) or 0.0)
        categories = risk_signals.get("categories", []) or []

        if "production_impact" in categories:
            risk_score = max(risk_score, 0.8)
        if "credential_access" in categories:
            risk_score = max(risk_score, 0.7)
        if "financial_consequence" in categories:
            risk_score = max(risk_score, 0.6)
        if "destructive_action" in categories:
            risk_score = max(risk_score, 0.5)
        if "admin_scope" in categories:
            risk_score = max(risk_score, 0.4)

        risk_signals["score"] = risk_score
        if hasattr(analysis, "__setitem__"):
            analysis["risk_signals"] = risk_signals
        else:
            analysis.risk_signals = risk_signals

        if risk_score >= 0.8:
            return RiskLevel.CRITICAL
        if risk_score >= 0.5:
            return RiskLevel.HIGH
        if risk_score >= 0.2:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def cortex_never_executes(self) -> bool:
        return True


_decider: Optional[CortexExecutionDecider] = None


def get_cortex_execution_decider() -> CortexExecutionDecider:
    global _decider
    if _decider is None:
        _decider = CortexExecutionDecider()
    return _decider

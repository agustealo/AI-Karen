from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.intelligence import get_intelligence_runtime
from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.reasoning.contracts import normalize_reasoning_modes
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

logger = logging.getLogger(__name__)

_FORCE_GRAPH_ENV = "KARI_RUNTIME_FORCE_GRAPH"
_SOFT_REASONING_MAX_MODEL_CALLS = 30


class CortexExecutionDecider:
    """Canonical cognitive executive for KAREN.

    CORTEX decides what the request appears to need. It does not authorize the
    decision and it never executes providers, tools, plugins, memory, graphs, or
    persistence. RuntimePolicy is invoked by Runtime after this decision returns.

    The returned ``ExecutionDecision`` therefore represents requested cognitive
    intent. Policy-owned fields remain empty/false until Runtime authorizes them.
    """

    def __init__(self, *, force_graph: Optional[bool] = None):
        self._force_graph = (
            force_graph
            if force_graph is not None
            else os.environ.get(_FORCE_GRAPH_ENV, "false").lower()
            in ("1", "true", "yes")
        )
        self._intelligence = get_intelligence_runtime()

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        meta = request.metadata or {}
        ctx = request.context
        reason_codes: List[str] = []

        user_content = str(meta.get("clarification_effective_query") or self._extract_user_content(request.messages))
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
        forbidden_capabilities = analysis.get("forbidden_capabilities", []) or list(
            meta.get("forbidden_capabilities") or []
        )

        if meta.get("agent_delegation"):
            analysis["agent_delegation"] = True
        if meta.get("workflow_required"):
            analysis["workflow_required"] = True

        if tool_requirements or plugin_candidates:
            if analysis.get("direct_capability", False):
                reason_codes.append("direct_capability_request")
            else:
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
            reason_codes.append("human_gate_recommended")
        if requires_agent_delegation:
            graph_required = True
            reason_codes.append("agent_delegation_required")

        # CORTEX owns the requested recall decision; the runtime still
        # authorizes any access through policy and tenant-scoped memory.
        # A live weather request without a named place needs user context,
        # regardless of whether Intelligence supplied a memory hint.
        capability_route = resolve_capability_decision(user_content)
        needs_location_recall = (
            analysis.get("intent") == "search.weather"
            and "location.current" in capability_route.missing_requirements
        )
        from ai_karen_engine.core.memory.signals.semantic_classifier import (
            is_personal_memory_recall_query,
        )
        personal_recall_query = is_personal_memory_recall_query(user_content)
        memory_recall_required = bool(
            analysis.get("memory_recall_required", False)
            or meta.get("memory_recall_required", False)
            or needs_location_recall
            or personal_recall_query
        )
        if personal_recall_query:
            reason_codes.append("explicit_personal_memory_recall")
            # Explicit user-profile recall wins over an unrelated ML intent label.
            # This only routes recall; RuntimePolicy still owns authorization.
            analysis["intent"] = "memory.recall"
            analysis["intent_confidence"] = 0.0
        memory_write_requested = bool(
            analysis.get("memory_write_requested", False)
            or meta.get("memory_write_requested", False)
        )
        from ai_karen_engine.core.memory.signals.semantic_classifier import (
            is_explicit_memory_save_request,
        )
        memory_write_requested = memory_write_requested or is_explicit_memory_save_request(user_content)
        if analysis.get("memory_write_denied", False):
            memory_write_requested = False

        memory_scope = (
            "user" if (needs_location_recall or personal_recall_query) else str(
                analysis.get("memory_scope", meta.get("memory_scope", "session"))
            )
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
        raw_reasoning_modes = (
            analysis.get("reasoning_modes") or meta.get("reasoning_modes") or []
        )
        if isinstance(raw_reasoning_modes, str):
            raw_reasoning_modes = [raw_reasoning_modes]
        reasoning_modes = normalize_reasoning_modes(list(raw_reasoning_modes))
        if (
            reasoning_depth == "deep" or analysis.get("reasoning_required")
        ) and not reasoning_modes:
            reasoning_modes = normalize_reasoning_modes(
                ["causal", "verification", "refinement", "metacognition"]
            )

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
        elif reasoning_modes:
            topology = ExecutionTopology.REASONING
        elif graph_required:
            topology = ExecutionTopology.WORKFLOW

        policy_constraints = dict(meta.get("policy_constraints") or {})
        policy_constraints.pop("personal_evidence_attribute", None)
        # The intelligence-owned resolver is deterministic and remains available
        # when ML analysis degrades or does not populate the semantic envelope.
        from ai_karen_engine.core.intelligence.profile_attribute import (
            requested_profile_attribute,
        )
        semantic_attribute = (
            requested_profile_attribute(user_content)
            if personal_recall_query else None
        )
        if personal_recall_query and semantic_attribute:
            policy_constraints["personal_evidence_attribute"] = semantic_attribute
        policy_constraints.update(
            {
                "memory_write_requested": memory_write_requested,
                "risk_signals": dict(analysis.get("risk_signals", {}) or {}),
                "current_domains": list(analysis.get("topics", []) or []),
                "max_model_calls": max_model_calls,
                "max_steps": max_steps,
                "direct_capability": bool(analysis.get("direct_capability", False)),
            }
        )

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
            memory_write_allowed=False,
            memory_scope=memory_scope,
            memory_top_k=memory_top_k,
            memory_classes=memory_classes,
            tool_requirements=tool_requirements,
            plugin_candidates=plugin_candidates,
            required_capabilities=requested_capabilities,
            forbidden_capabilities=forbidden_capabilities,
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
            policy_decision_id=None,
            policy_version="",
            policy_reason_codes=[],
            reason_codes=reason_codes,
            policy_constraints=policy_constraints,
        )

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

        capability_decision = resolve_capability_decision(text)

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
            # Consume the canonical Intelligence interpretation as an evidence
            # request, not as an authorization or a new model-routing decision.
            interpretation = getattr(analysis, "interpretation", None)
            evidence_needs = tuple(
                str(source).casefold()
                for source in (getattr(interpretation, "evidence_needs", ()) or ())
            )
            if "memory" in evidence_needs:
                memory_policy["recall_required"] = True
                memory_policy["scope"] = "user"
            if self._personal_recall_query(text) or "location.current" in capability_decision.missing_requirements:
                memory_policy["recall_required"] = True
                memory_policy["scope"] = "user"
                memory_policy["top_k"] = max(15, memory_policy["top_k"])
            workflow = self._infer_workflow_from_analysis(analysis)
            risk_level = self._assess_risk_level(analysis)

            capability_decision = resolve_capability_decision(
                text,
                confidence=float(confidence),
            )
            direct_capability = self._apply_direct_capability_route(
                capability_decision,
                topology=topology,
                capabilities=capabilities,
            )
            raw_modes = getattr(analysis, "reasoning_modes", []) or []
            if isinstance(raw_modes, str):
                raw_modes = [raw_modes]
            reasoning_modes = normalize_reasoning_modes(list(raw_modes))

            # Compatibility feature extraction. These deterministic hints are
            # scheduled to move under Intelligence; CORTEX only consumes their
            # resulting tool requirement until that migration is complete.
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
                "intent": (
                    capability_decision.intent
                    if direct_capability
                    else intent_value
                ),
                "intent_confidence": (
                    max(float(confidence), float(capability_decision.confidence))
                    if direct_capability
                    else confidence
                ),
                "direct_capability": direct_capability,
                "task_complexity": getattr(analysis, "task_complexity", "simple"),
                "topics": list(getattr(analysis, "topics", []) or []),
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
                "requested_profile_attribute": getattr(getattr(analysis, "interpretation", None), "requested_profile_attribute", None),
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
                "risk_level": risk_level.value,
                "risk_score": (getattr(analysis, "risk_signals", {}) or {}).get(
                    "score", 0.0
                ),
                "risk_categories": (
                    getattr(analysis, "risk_signals", {}) or {}
                ).get("categories", []),
            }
        except Exception as exc:
            logger.warning("CORTEX analysis failed, using safe defaults: %s", exc)
            fallback = self._default_analysis()
            topology = {
                "tool_requirements": fallback["tool_requirements"],
                "plugin_candidates": fallback["plugin_candidates"],
            }
            capabilities = {
                "required": fallback["required_capabilities"],
                "forbidden": fallback["forbidden_capabilities"],
            }
            direct_capability = self._apply_direct_capability_route(
                capability_decision,
                topology=topology,
                capabilities=capabilities,
            )
            if direct_capability:
                fallback["intent"] = capability_decision.intent
                fallback["intent_confidence"] = float(
                    capability_decision.confidence
                )
                fallback["direct_capability"] = True
            if self._personal_recall_query(text):
                fallback["intent"] = "memory.recall"
                fallback["intent_confidence"] = 0.0
                from ai_karen_engine.core.intelligence.profile_attribute import (
                    requested_profile_attribute,
                )
                fallback["requested_profile_attribute"] = requested_profile_attribute(text)
            if self._personal_recall_query(text) or "location.current" in capability_decision.missing_requirements:
                fallback["memory_recall_required"] = True
                fallback["memory_scope"] = "user"
                fallback["memory_top_k"] = 15
            return fallback

    @staticmethod
    def _personal_recall_query(text: str) -> bool:
        """Delegate recognition to Intelligence's canonical memory signals."""
        from ai_karen_engine.core.memory.signals.semantic_classifier import (
            is_personal_memory_recall_query,
        )

        return is_personal_memory_recall_query(text)

    @staticmethod
    def _apply_direct_capability_route(
        capability_decision: Any,
        *,
        topology: Dict[str, Any],
        capabilities: Dict[str, Any],
    ) -> bool:
        if not capability_decision.requires_tool:
            return False

        preferred_plugin = str(
            capability_decision.preferred_plugin or ""
        ).strip()
        handler = str(capability_decision.handler or "").strip()
        required_capability = str(
            capability_decision.capability or ""
        ).strip()

        plugin_candidates = topology.setdefault("plugin_candidates", [])
        if preferred_plugin and preferred_plugin not in plugin_candidates:
            plugin_candidates.append(preferred_plugin)

        # Time Query is the governed time authority. Do not invent a parallel
        # time tool because the compatibility route still exposes an old label.
        tool_requirements = topology.setdefault("tool_requirements", [])
        if (
            handler
            and capability_decision.intent != "time.current"
            and handler not in tool_requirements
        ):
            tool_requirements.append(handler)

        required = capabilities.setdefault("required", [])
        if required_capability and required_capability not in required:
            required.append(required_capability)

        return True

    def _default_analysis(self) -> Dict[str, Any]:
        return {
            "intent": "general_assist",
            "intent_confidence": 0.0,
            "task_complexity": "simple",
            "topics": [],
            "memory_relevance": 0.0,
            "topology_signals": {},
            "risk_signals": {"categories": [], "score": 0.0},
            "capability_hints": {},
            "direct_capability": False,
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

        # Complexity may increase reasoning budget, but it is not by itself a
        # workflow/graph semantic. This preserves LangGraph for real workflows.
        if task_complexity == "complex":
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
        if topology_signals.get("dependency_chain") or topology_signals.get(
            "multiple_actions"
        ):
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

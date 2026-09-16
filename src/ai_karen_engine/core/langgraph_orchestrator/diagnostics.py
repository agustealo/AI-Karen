"""Diagnostics module.

Provides side-effect-free preflight analysis from canonical Runtime/CORTEX
decision truth. Diagnostics never selects providers, executes providers,
classifies intent independently, or invents fallback model metadata.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.composition import get_runtime_composition
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline

logger = logging.getLogger(__name__)


class DiagnosticsEngine:
    """Produce preflight diagnostics from canonical runtime decision authority."""

    def __init__(
        self,
        *,
        decision_pipeline: Optional[RuntimeDecisionPipeline] = None,
    ) -> None:
        self._decision_pipeline = (
            decision_pipeline or get_runtime_composition().decision_pipeline
        )

    async def run_dry_run_analysis(
        self,
        *,
        message: str,
        session_id: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyze a request without provider execution or persistence side effects."""

        user = user or {}
        context = context or {}

        user_id = str(user.get("id") or user.get("user_id") or "").strip()
        tenant_id = str(
            user.get("tenant_id")
            or user.get("organization_id")
            or context.get("tenant_id")
            or ""
        ).strip()

        if not user_id:
            raise PermissionError("Diagnostics requires explicit authenticated user_id")
        if not tenant_id or tenant_id == "default":
            raise PermissionError("Diagnostics requires explicit non-default tenant_id")

        session_identifier = str(
            session_id or context.get("session_id") or f"dryrun-{uuid.uuid4()}"
        )
        request_id = str(context.get("request_id") or uuid.uuid4())
        correlation_id = str(context.get("correlation_id") or uuid.uuid4())

        conversation_history = context.get("conversation_history")
        if not isinstance(conversation_history, list):
            conversation_history = []

        messages: List[Dict[str, Any]] = []
        for entry in conversation_history:
            if isinstance(entry, dict) and entry.get("content") is not None:
                messages.append(
                    {
                        "role": str(entry.get("role") or "user"),
                        "content": str(entry.get("content") or ""),
                    }
                )
        messages.append({"role": "user", "content": message})

        roles = user.get("roles") or context.get("roles") or []
        permissions = user.get("permissions") or context.get("permissions") or []

        request = ChatExecutionRequest(
            messages=messages,
            context=ChatExecutionContext(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_identifier,
                conversation_id=str(context.get("conversation_id") or session_identifier),
                request_id=request_id,
                correlation_id=correlation_id,
                roles=[str(value) for value in roles],
                permissions=[str(value) for value in permissions],
            ),
            preferred_provider=(
                str(context.get("preferred_provider"))
                if context.get("preferred_provider")
                else None
            ),
            preferred_model=(
                str(context.get("preferred_model"))
                if context.get("preferred_model")
                else None
            ),
            temperature=float(context.get("temperature", 0.7)),
            max_tokens=(
                int(context["max_tokens"])
                if context.get("max_tokens") is not None
                else None
            ),
            stream=False,
            metadata={"diagnostic_dry_run": True},
        )

        decision = await self._decision_pipeline.decide(request)

        required_tools = [str(value) for value in decision.tool_requirements]
        tool_calls = [{"tool": tool, "parameters": {}} for tool in required_tools]

        execution_plan = {
            "intent": decision.intent,
            "intent_confidence": decision.intent_confidence,
            "topology": (
                decision.topology.value
                if hasattr(decision.topology, "value")
                else str(decision.topology)
            ),
            "execution_mode": (
                decision.execution_mode.value
                if hasattr(decision.execution_mode, "value")
                else str(decision.execution_mode)
            ),
            "reasoning_depth": decision.reasoning_depth,
            "reasoning_modes": list(decision.reasoning_modes),
            "required_capabilities": list(decision.required_capabilities),
            "forbidden_capabilities": list(decision.forbidden_capabilities),
            "tool_requirements": required_tools,
            "plugin_candidates": list(decision.plugin_candidates),
            "requires_human_review": decision.requires_human_gate,
            "requires_resumability": decision.requires_resumability,
            "requires_parallel_execution": decision.requires_parallel_execution,
            "requires_agent_delegation": decision.requires_agent_delegation,
            "workflow_id": decision.workflow_id,
            "workflow_version": decision.workflow_version,
            "max_steps": decision.max_steps,
            "max_model_calls": decision.max_model_calls,
            "time_budget_ms": decision.time_budget_ms,
            "token_budget": decision.token_budget,
            "policy_decision_id": decision.policy_decision_id,
            "policy_version": decision.policy_version,
            "policy_reason_codes": list(decision.policy_reason_codes),
            "reason_codes": list(decision.reason_codes),
        }

        memories_considered = 0
        cognitive_context = decision.cognitive_context
        if cognitive_context is not None:
            resolved = getattr(cognitive_context, "resolved_context", None)
            if isinstance(resolved, dict):
                recall = resolved.get("memory") or resolved.get("recall") or []
                if isinstance(recall, list):
                    memories_considered = len(recall)

        return {
            "session_id": session_identifier,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "message": message,
            "predicted_intent": decision.intent,
            "intent_confidence": decision.intent_confidence,
            "routing_reason": (
                "Provider/model intentionally unresolved in diagnostics; "
                "Runtime owns execution-time routing"
            ),
            "routing_confidence": 0.0,
            "predicted_provider": None,
            "predicted_model": None,
            "estimated_processing_time": decision.time_budget_ms / 1000.0,
            "required_tools": required_tools,
            "tool_parameters": tool_calls,
            "execution_plan": execution_plan,
            "safety_assessment": {
                "status": "governed_by_runtime_policy",
                "risk_level": (
                    decision.risk_level.value
                    if hasattr(decision.risk_level, "value")
                    else str(decision.risk_level)
                ),
                "policy_reason_codes": list(decision.policy_reason_codes),
            },
            "approval_required": decision.requires_human_gate,
            "context_summary": None,
            "memories_considered": memories_considered,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_preferences": {},
        }

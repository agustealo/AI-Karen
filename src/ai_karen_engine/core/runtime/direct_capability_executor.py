from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.cortex.routing_intents import CAPABILITY_ROUTES
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
    ExecutionBudgetMeter,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.services.plugin_service import (
    ExecutionStatus,
    get_plugin_service,
)
from ai_karen_engine.services.tooling.tool_service import (
    ToolInput,
    get_tool_service,
)


@dataclass(slots=True)
class DirectCapabilityResult:
    """Runtime-owned result for one governed, single-step capability."""

    handled: bool
    text: str = ""
    success: bool = False
    degraded: bool = False
    source: Optional[str] = None
    source_id: Optional[str] = None
    error: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    attempts: List[Dict[str, Any]] = field(default_factory=list)

    def normalized_metadata(self) -> Dict[str, Any]:
        return {
            "actual_provider": self.source_id,
            "actual_model": None,
            "runtime_engine": "direct_capability",
            "response_source": self.source or "capability_unavailable",
            "fallback_level": max(0, len(self.attempts) - 1),
            "degraded_mode": self.degraded,
            "degradation_reason": self.error,
            "provider_attempts": list(self.attempts),
            "structured_content": dict(self.payload),
            "sources": list(self.sources),
            "citations": list(self.citations),
            "execution_spans": [
                {
                    "name": "direct_capability",
                    "duration_ms": self.latency_ms,
                    "source": self.source or "capability_unavailable",
                }
            ],
        }


class DirectCapabilityExecutor:
    """Execute simple live capabilities without forcing a LangGraph workflow.

    CORTEX decides the capability. RuntimePolicy authorizes the concrete plugin
    and tool candidates in the AuthorizedExecutionPlan. This executor only
    executes that already-authorized single-step plan.
    """

    def can_handle(self, decision: ExecutionDecision) -> bool:
        route = CAPABILITY_ROUTES.get(str(decision.intent or ""))
        return bool(route and route.get("requires_live_data"))

    async def execute(
        self,
        *,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
    ) -> DirectCapabilityResult:
        route = CAPABILITY_ROUTES.get(str(decision.intent or ""))
        if not route:
            return DirectCapabilityResult(handled=False)

        started = time.perf_counter()
        query = self._latest_user_text(request)
        capability = str(route.get("required_capability") or "").strip()
        preferred_plugin = str(route.get("preferred_plugin") or "").strip()
        tool_name = str(route.get("handler") or "").strip()
        mode = str(route.get("plugin_mode") or "").strip() or None
        attempts: List[Dict[str, Any]] = []

        if preferred_plugin and preferred_plugin in set(plan.allowed_plugins):
            if await ActionExecutionGate.authorize(plan, preferred_plugin):
                if not await meter.consume_tool_call():
                    return self._unavailable(
                        started,
                        capability,
                        preferred_plugin,
                        "Execution budget exhausted before plugin execution.",
                        attempts,
                    )

                plugin_started = time.perf_counter()
                plugin_result = await get_plugin_service().execute_plugin(
                    preferred_plugin,
                    parameters=self._plugin_parameters(
                        decision.intent,
                        query,
                        request,
                        mode,
                    ),
                    user_id=request.context.user_id,
                    tenant_id=request.context.tenant_id,
                    session_id=request.context.session_id,
                    conversation_id=request.context.conversation_id,
                    correlation_id=request.context.correlation_id,
                    roles=list(request.context.roles or []),
                    permissions=list(request.context.permissions or []),
                    policy_decision_id=plan.policy_decision_id,
                    authorized_plan=plan,
                    allowed_capabilities=list(plan.allowed_capabilities),
                    forbidden_capabilities=list(decision.forbidden_capabilities),
                )
                plugin_ok = plugin_result.status is ExecutionStatus.COMPLETED
                attempts.append(
                    {
                        "type": "plugin",
                        "id": preferred_plugin,
                        "status": "success" if plugin_ok else "failed",
                        "error": plugin_result.error,
                        "latency_ms": (
                            time.perf_counter() - plugin_started
                        )
                        * 1000.0,
                    }
                )
                if plugin_ok:
                    payload = self._normalize_payload(plugin_result.result)
                    return self._success(
                        started,
                        decision.intent,
                        query,
                        payload,
                        source="plugin",
                        source_id=preferred_plugin,
                        attempts=attempts,
                    )

        if decision.intent == "time.current":
            reason = self._last_attempt_error(
                attempts,
                "Time Query is not authorized or available for this chat.",
            )
            return self._unavailable(
                started,
                capability,
                preferred_plugin or "time-query",
                reason,
                attempts,
            )

        if tool_name and tool_name in set(plan.allowed_tools):
            if await ActionExecutionGate.authorize(plan, tool_name):
                if not await meter.consume_tool_call():
                    return self._unavailable(
                        started,
                        capability,
                        tool_name,
                        "Execution budget exhausted before tool execution.",
                        attempts,
                    )

                tool_started = time.perf_counter()
                tool_result = await get_tool_service().execute_tool(
                    ToolInput(
                        tool_name=tool_name,
                        parameters=self._tool_parameters(query, mode),
                        user_context={
                            "tenant_id": request.context.tenant_id,
                            "conversation_id": request.context.conversation_id,
                            "correlation_id": request.context.correlation_id,
                            "allowed_capabilities": list(plan.allowed_capabilities),
                        },
                        user_id=request.context.user_id,
                        session_id=request.context.session_id,
                        request_id=request.context.request_id
                        or request.context.correlation_id,
                    )
                )
                attempts.append(
                    {
                        "type": "tool",
                        "id": tool_name,
                        "status": "success" if tool_result.success else "failed",
                        "error": tool_result.error,
                        "latency_ms": (
                            time.perf_counter() - tool_started
                        )
                        * 1000.0,
                    }
                )
                if tool_result.success:
                    payload = self._normalize_payload(tool_result.result)
                    return self._success(
                        started,
                        decision.intent,
                        query,
                        payload,
                        source="tool",
                        source_id=tool_name,
                        attempts=attempts,
                    )

        target = preferred_plugin or tool_name or capability or "live capability"
        reason = self._last_attempt_error(
            attempts,
            f"{target} is not authorized or available for this chat.",
        )
        return self._unavailable(
            started,
            capability,
            target,
            reason,
            attempts,
        )

    @staticmethod
    def _latest_user_text(request: ChatExecutionRequest) -> str:
        for message in reversed(request.messages):
            if str(message.get("role") or "").lower() == "user":
                return str(message.get("content") or "").strip()
        return ""

    @staticmethod
    def _normalize_payload(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {"value": value}

    def _success(
        self,
        started: float,
        intent: str,
        query: str,
        payload: Dict[str, Any],
        *,
        source: str,
        source_id: str,
        attempts: List[Dict[str, Any]],
    ) -> DirectCapabilityResult:
        text = self._render(intent, query, payload)
        sources = [
            item for item in list(payload.get("sources") or []) if isinstance(item, dict)
        ]
        citations = [
            item
            for item in list(payload.get("citations") or [])
            if isinstance(item, dict)
        ]
        degraded = bool(
            payload.get("status") in {"error", "degraded"}
            or (payload.get("metadata") or {}).get("degraded")
        )
        return DirectCapabilityResult(
            handled=True,
            text=text,
            success=bool(text),
            degraded=degraded,
            source=source,
            source_id=source_id,
            payload=payload,
            sources=sources,
            citations=citations,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            attempts=attempts,
        )

    def _unavailable(
        self,
        started: float,
        capability: str,
        target: str,
        reason: str,
        attempts: List[Dict[str, Any]],
    ) -> DirectCapabilityResult:
        capability_label = capability or "live data"
        target_label = target or "the required capability"
        text = (
            f"I can handle that autonomously, but {target_label} could not run "
            f"for this chat. Required capability: {capability_label}. "
            "If web/plugin access is disabled, enable it and I can retry the "
            "request directly."
        )
        return DirectCapabilityResult(
            handled=True,
            text=text,
            success=False,
            degraded=True,
            source="capability_unavailable",
            source_id=target_label,
            error=reason,
            payload={
                "required_capability": capability_label,
                "target": target_label,
                "next_action": "enable_or_authorize_capability",
            },
            latency_ms=(time.perf_counter() - started) * 1000.0,
            attempts=attempts,
        )

    @staticmethod
    def _last_attempt_error(
        attempts: List[Dict[str, Any]],
        default: str,
    ) -> str:
        for attempt in reversed(attempts):
            error = str(attempt.get("error") or "").strip()
            if error:
                return error
        return default

    @staticmethod
    def _tool_parameters(query: str, mode: Optional[str]) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": query}
        if mode:
            params["mode"] = mode
        return params

    def _plugin_parameters(
        self,
        intent: str,
        query: str,
        request: ChatExecutionRequest,
        mode: Optional[str],
    ) -> Dict[str, Any]:
        if intent == "time.current":
            location = self._extract_time_location(query)
            if location:
                return {
                    "mode": "world_time",
                    "query": location,
                    "context": dict(request.metadata or {}),
                }

            timezone_name = self._metadata_timezone(request.metadata)
            params: Dict[str, Any] = {
                "mode": "time",
                "context": dict(request.metadata or {}),
            }
            if timezone_name:
                params["timezone"] = timezone_name
            return params

        params = {
            "query": query,
            "context": dict(request.metadata or {}),
        }
        if mode:
            params["mode"] = mode
        return params

    @staticmethod
    def _extract_time_location(query: str) -> Optional[str]:
        patterns = (
            r"\btime\s+(?:is\s+it\s+)?in\s+(.+?)[?!.]*$",
            r"\bcurrent\s+time\s+in\s+(.+?)[?!.]*$",
        )
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                location = match.group(1).strip(" ,")
                if location:
                    return location
        return None

    @staticmethod
    def _metadata_timezone(metadata: Dict[str, Any]) -> Optional[str]:
        for key in ("timezone", "user_timezone", "local_timezone"):
            value = str((metadata or {}).get(key) or "").strip()
            if value:
                return value
        return None

    def _render(self, intent: str, query: str, payload: Dict[str, Any]) -> str:
        if intent == "time.current":
            value = (
                payload.get("value")
                or payload.get("formatted")
                or payload.get("time")
                or payload.get("iso")
            )
            label = (
                payload.get("label")
                or payload.get("query_location")
                or payload.get("resolved_timezone")
                or payload.get("timezone")
            )
            if value:
                if label:
                    return f"The current time in {label} is {value}."
                return f"The current time is {value}."

        if intent in {"search.weather", "search.general"}:
            extracted = payload.get("extractedData")
            if isinstance(extracted, dict) and extracted:
                compact = ", ".join(
                    f"{key}: {value}"
                    for key, value in list(extracted.items())[:8]
                    if value not in (None, "", [], {})
                )
                if compact:
                    return compact

            results = [
                item
                for item in list(payload.get("results") or [])
                if isinstance(item, dict)
            ]
            snippets = [
                str(item.get("snippet") or item.get("content") or "").strip()
                for item in results[:3]
            ]
            snippets = [snippet for snippet in snippets if snippet]
            if snippets:
                prefix = (
                    "Here’s the live weather information I found:"
                    if intent == "search.weather"
                    else "Here’s what I found live:"
                )
                return prefix + "\n\n" + "\n\n".join(snippets)

            summary = str(payload.get("summary") or "").strip()
            if summary:
                return summary

        value = payload.get("value")
        if value not in (None, ""):
            return str(value)

        summary = str(payload.get("summary") or "").strip()
        if summary:
            return summary

        return (
            f"I ran the live capability for '{query}', but it returned no "
            "user-readable result."
        )


_direct_capability_executor: Optional[DirectCapabilityExecutor] = None


def get_direct_capability_executor() -> DirectCapabilityExecutor:
    global _direct_capability_executor
    if _direct_capability_executor is None:
        _direct_capability_executor = DirectCapabilityExecutor()
    return _direct_capability_executor

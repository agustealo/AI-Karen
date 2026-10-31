from __future__ import annotations

import re
import time
import uuid
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
        presentation_payload = {
            key: self.payload.get(key)
            for key in (
                "query",
                "mode",
                "status",
                "value",
                "formatted",
                "time",
                "date",
                "timezone",
                "resolved_timezone",
                "label",
                "extractedData",
                "insights",
                "required_capability",
                "target",
                "next_action",
                "provider",
                "search_providers",
                "crawl_provider",
                "timer_receipt",
            )
            if self.payload.get(key) is not None
        }
        payload_metadata = self.payload.get("metadata")
        payload_metadata = (
            payload_metadata if isinstance(payload_metadata, dict) else {}
        )
        for key in ("provider", "search_providers", "crawl_provider"):
            if (
                presentation_payload.get(key) is None
                and payload_metadata.get(key) is not None
            ):
                presentation_payload[key] = payload_metadata[key]

        reported_provider = str(
            self.payload.get("provider")
            or payload_metadata.get("provider")
            or ""
        ).strip()
        # Search backends and tool/plugin identifiers are not chat model
        # providers. Never misrepresent web_search as a replacement for Ollama.
        return {
            "actual_provider": None,
            "capability_executor": self.source_id,
            "capability_data_provider": (
                reported_provider
                if reported_provider and reported_provider != "none"
                else None
            ),
            "actual_model": None,
            "runtime_engine": "direct_capability",
            "response_source": self.source or "capability_unavailable",
            "fallback_level": 0,
            "degraded_mode": self.degraded,
            "degradation_reason": self.error,
            "provider_attempts": list(self.attempts),
            "structured_content": presentation_payload,
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

    @staticmethod
    def _timer_unavailable(reason: str, message: str) -> DirectCapabilityResult:
        return DirectCapabilityResult(
            handled=True, text=message, success=False, degraded=True,
            source="capability_unavailable", source_id="timer.schedule",
            error=reason,
            payload={
                "status": "unavailable",
                "required_capability": "timer.schedule",
                "scheduler_verified": False,
                "timer_created": False,
                "reminder_delivered": False,
            },
            attempts=[{
                "type": "capability", "id": "timer.schedule",
                "status": "unavailable", "error": reason,
            }],
        )

    async def _execute_timer(
        self,
        request: ChatExecutionRequest,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
    ) -> DirectCapabilityResult:
        """One canonical owner for chat timer admission and receipt truth.

        The SQL timer ledger records durable deadlines, not notification jobs.
        Never infer delivery, pause/resume support or an active state from prose.
        """
        from ai_karen_engine.services.automation.timers import (
            OwnedTimerService, TimerAuthorizationError, TimerNotFoundError,
        )

        unavailable = self._timer_unavailable
        if "timer.schedule" not in set(plan.allowed_capabilities):
            return unavailable("timer_not_authorized", "Timer access is not authorized for this request. No timer was started.")
        try:
            principal = request.context.require_authenticated_user()
        except PermissionError:
            return unavailable("timer_principal_unverified", "Timer identity could not be verified. No timer was started.")
        if not await meter.consume_tool_call():
            return unavailable("timer_budget_exhausted", "Timer execution budget is exhausted. No timer was started.")

        query = self._latest_user_text(request).strip()
        normalized = " ".join(query.lower().split()).rstrip("?! .")
        # A reminder request is not a countdown command. Do not even claim it
        # was queued: this service has no worker or delivery receipt.
        if re.search(r"\b(remind|reminder|notify|notification)\b", normalized):
            return unavailable(
                "timer_notification_unavailable",
                "I cannot verify any timer reminder was scheduled or delivered. "
                "Countdown storage does not send notifications.",
            )

        started = time.perf_counter()
        service = OwnedTimerService()
        correlation = str(request.context.correlation_id or "")
        try:
            if re.match(r"^(?:please\s+)?(?:start|set|create|begin)\b", normalized):
                match = re.search(
                    r"\b(\d{1,5})\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
                    normalized,
                )
                if not match:
                    return unavailable("timer_duration_missing", "Specify a timer duration in seconds, minutes or hours. No timer was started.")
                quantity = int(match.group(1))
                unit = match.group(2)
                factor = 3600 if unit.startswith(("hour", "hr")) else 60 if unit.startswith(("minute", "min")) else 1
                seconds = quantity * factor
                if seconds < 1 or seconds > 86400:
                    return unavailable("timer_duration_invalid", "Timer duration must be from 1 second through 24 hours. No timer was started.")
                stable_id = str(request.context.request_id or correlation).strip()
                if not stable_id or not correlation:
                    return unavailable("timer_request_identity_missing", "A verified timer request ID is required. No timer was started.")
                # Stable retry identity scoped to the authenticated request.
                key = uuid.uuid5(uuid.NAMESPACE_URL,
                    ":".join(("karen-timer-v1", str(principal.tenant_id),
                              str(principal.user_id),
                              request.context.require_conversation_id(), stable_id)))
                receipt = await service.create(
                    user=principal, duration_seconds=seconds, title="Timer",
                    idempotency_key=key, correlation_id=correlation,
                )
                verb = "started" if receipt["status"] == "active" else receipt["status"]
                message = (
                    f"Timer {verb}. ID: {receipt['timer_id']}. "
                    f"Deadline: {receipt['deadline_at']}. "
                    "No reminder or notification has been scheduled."
                )
            elif re.match(r"^(?:please\s+)?(?:cancel|stop)\b", normalized):
                available = await service.list(user=principal, correlation_id=correlation)
                active = next((row for row in available if row["status"] == "active"), None)
                if active is None:
                    return unavailable("timer_not_found", "There is no active timer to cancel.")
                receipt = await service.cancel(
                    user=principal, timer_id=uuid.UUID(active["timer_id"]),
                    correlation_id=correlation,
                )
                message = (
                    f"Timer status: {receipt['status']}. ID: {receipt['timer_id']}. "
                    f"Deadline: {receipt['deadline_at']}. "
                    "No reminder delivery is confirmed."
                )
            elif re.match(r"^(?:please\s+)?(?:show|display|open|is|has|what|can|could|would)\b", normalized):
                available = await service.list(user=principal, correlation_id=correlation)
                if not available:
                    return unavailable("timer_not_found", "No saved countdown timer was found for your account.")
                receipt = next((row for row in available if row["status"] == "active"), available[0])
                message = (
                    f"Timer status: {receipt['status']}. ID: {receipt['timer_id']}. "
                    f"Deadline: {receipt['deadline_at']}. "
                    "This is a saved countdown deadline, not a notification."
                )
            else:
                return unavailable(
                    "timer_action_unsupported",
                    "This timer action is not supported by the durable countdown service. "
                    "No timer was changed.",
                )
        except (TimerAuthorizationError, TimerNotFoundError, ValueError):
            return unavailable("timer_scope_or_input_denied", "Timer access or requested action could not be verified. No timer change is confirmed.")
        except Exception as exc:
            # Database unavailable, migration missing or audit failure must
            # never become a model-generated success or another scheduler.
            import logging
            logging.getLogger(__name__).warning(
                "timer_action_unavailable",
                extra={"correlation_id": correlation, "error_type": type(exc).__name__},
            )
            return unavailable("timer_persistence_unavailable", "Timer storage is unavailable. No timer change is confirmed.")

        return DirectCapabilityResult(
            handled=True, success=True, degraded=False,
            text=message, source="durable_timer_ledger",
            source_id="timer.schedule",
            payload={
                "status": receipt["status"],
                "timer_receipt": receipt,
                "required_capability": "timer.schedule",
                "timer_created": receipt["status"] == "active" and
                    bool(re.match(r"^(?:please\s+)?(?:start|set|create|begin)\b", normalized)),
                "reminder_delivered": False,
            },
            attempts=[{
                "type": "capability", "id": "timer.schedule",
                "status": "success", "source": "postgresql_timer_ledger",
            }],
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def can_handle(self, decision: ExecutionDecision) -> bool:
        route = CAPABILITY_ROUTES.get(str(decision.intent or ""))
        if not route or not route.get("requires_live_data"):
            return False
        if decision.is_graph_required:
            return False
        policy_constraints = getattr(decision, "policy_constraints", {}) or {}
        return bool(policy_constraints.get("direct_capability", False))

    async def execute(
        self,
        *,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        meter: ExecutionBudgetMeter,
        resolved_context: Optional[Dict[str, Any]] = None,
    ) -> DirectCapabilityResult:
        route = CAPABILITY_ROUTES.get(str(decision.intent or ""))
        if not route:
            return DirectCapabilityResult(handled=False)

        if decision.intent == "timer.manage":
            return await self._execute_timer(request, plan, meter)

        if decision.intent == "planner.read":
            from ai_karen_engine.config.runtime import get_runtime_settings
            from ai_karen_engine.services.personal_planner import PersonalPlannerService

            started_at = time.perf_counter()
            if not get_runtime_settings().enable_personal_planner_read_api:
                return DirectCapabilityResult(
                    handled=True, text="Planner reads are disabled.",
                    error="planner_read_disabled", degraded=True,
                )
            if "planner.read" not in set(plan.allowed_capabilities):
                return DirectCapabilityResult(
                    handled=True, text="Planner read is not authorized for this request.",
                    error="planner_read_not_authorized", degraded=True,
                )
            try:
                principal = request.context.require_authenticated_user()
                if not await meter.consume_tool_call():
                    return DirectCapabilityResult(
                        handled=True, text="Planner read budget exhausted.",
                        error="execution_budget_exhausted", degraded=True,
                    )
                output = await PersonalPlannerService().list_presentation(
                    user=principal,
                    correlation_id=request.context.correlation_id,
                    limit=20,
                )
            except (PermissionError, ValueError) as exc:
                return DirectCapabilityResult(
                    handled=True, text="Planner access unavailable.",
                    error=type(exc).__name__, degraded=True,
                )
            tasks = (output.get("presentation") or {}).get("data", {}).get("tasks", [])
            return DirectCapabilityResult(
                handled=True, success=True, source="planner",
                source_id="planner.read",
                text=(f"Found {len(tasks)} planner commitments." if tasks else "No planner commitments found."),
                payload={"presentation": output.get("presentation"), "empty": output.get("empty", False)},
                attempts=[{"type": "planner", "id": "planner.read", "status": "success"}],
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
            )

        started = time.perf_counter()
        query = self._latest_user_text(request)
        capability = str(route.get("required_capability") or "").strip()
        preferred_plugin = str(route.get("preferred_plugin") or "").strip()
        tool_name = str(route.get("handler") or "").strip()
        mode = str(route.get("plugin_mode") or "").strip() or None
        attempts: List[Dict[str, Any]] = []

        if decision.intent == "search.weather":
            from ai_karen_engine.core.runtime.location_context import resolve_location
            # Preserve the existing explicit clarification-answer flow without
            # treating arbitrary metadata location hints as authorized.
            selected = resolve_location(request.metadata, resolved_context, kind="weather")
            effective_context = (
                {"weather_location": selected.value, "location_source": selected.source}
                if selected else {}
            )
            pending = (request.metadata or {}).get("pending_clarification")
            if isinstance(pending, dict):
                effective_context["pending_clarification"] = pending
            resolved = self._weather_query_with_location(query, effective_context)
            if resolved is None:
                return DirectCapabilityResult(
                    handled=True,
                    text="Which city or location should I check the weather for?",
                    success=True,
                    source="missing_context",
                    source_id="weather_location",
                    payload={
                        "status": "needs_input",
                        "required_capability": capability,
                        "missing_requirement": "weather_location",
                        "next_action": "ask_location",
                    },
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )
            query = resolved

        async def run_tool() -> Optional[DirectCapabilityResult]:
            if not tool_name:
                return None
            if tool_name not in set(plan.allowed_tools):
                attempts.append({"type": "tool", "id": tool_name, "status": "skipped", "error": "not_in_authorized_plan"})
                return None
            if not await ActionExecutionGate.authorize(plan, tool_name):
                attempts.append({"type": "tool", "id": tool_name, "status": "denied", "error": "execution_gate_denied"})
                return None
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
                        "request_id": (
                            request.context.request_id
                            or request.context.correlation_id
                        ),
                        "user_id": request.context.user_id,
                        "tenant_id": request.context.tenant_id,
                        "session_id": request.context.session_id,
                        "conversation_id": request.context.conversation_id,
                        "correlation_id": request.context.correlation_id,
                        "allowed_capabilities": list(plan.allowed_capabilities),
                        "authorized_plan": plan,
                        "policy_decision_id": plan.policy_decision_id,
                    },
                    user_id=request.context.user_id,
                    session_id=request.context.session_id,
                    request_id=(
                        request.context.request_id
                        or request.context.correlation_id
                    ),
                )
            )
            payload = self._normalize_payload(tool_result.result)
            tool_ok = bool(
                tool_result.success
                and self._payload_succeeded(decision.intent, payload)
            )
            tool_error = (
                tool_result.error
                or payload.get("error")
                or payload.get("reason")
                or (
                    None
                    if tool_ok
                    else "capability_returned_no_live_data"
                )
            )
            attempts.append(
                {
                    "type": "tool",
                    "id": tool_name,
                    "status": "success" if tool_ok else "failed",
                    "error": tool_error,
                    "latency_ms": (
                        time.perf_counter() - tool_started
                    )
                    * 1000.0,
                }
            )
            if not tool_ok:
                return None
            return self._success(
                started,
                decision.intent,
                query,
                payload,
                source="tool",
                source_id=tool_name,
                attempts=attempts,
            )

        async def run_plugin() -> Optional[DirectCapabilityResult]:
            if not preferred_plugin:
                return None
            if preferred_plugin not in set(plan.allowed_plugins):
                attempts.append({"type": "plugin", "id": preferred_plugin, "status": "skipped", "error": "not_in_authorized_plan"})
                return None
            if not await ActionExecutionGate.authorize(plan, preferred_plugin):
                attempts.append({"type": "plugin", "id": preferred_plugin, "status": "denied", "error": "execution_gate_denied"})
                return None
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
                    resolved_context,
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
            payload = self._normalize_payload(plugin_result.result)
            plugin_ok = (
                plugin_result.status is ExecutionStatus.COMPLETED
                and self._payload_succeeded(decision.intent, payload)
            )
            plugin_error = (
                plugin_result.error
                or payload.get("error")
                or payload.get("reason")
                or (
                    None
                    if plugin_ok
                    else "capability_returned_no_live_data"
                )
            )
            attempts.append(
                {
                    "type": "plugin",
                    "id": preferred_plugin,
                    "status": "success" if plugin_ok else "failed",
                    "error": plugin_error,
                    "latency_ms": (
                        time.perf_counter() - plugin_started
                    )
                    * 1000.0,
                }
            )
            if not plugin_ok:
                return None
            return self._success(
                started,
                decision.intent,
                query,
                payload,
                source="plugin",
                source_id=preferred_plugin,
                attempts=attempts,
            )

        if decision.intent == "system.resources":
            result = await run_tool()
            if result is not None:
                return result
            return self._unavailable(started, capability, tool_name, "Resource tool unavailable or unauthorized.", attempts)

        if decision.intent == "time.current":
            result = await run_plugin()
            if result is not None:
                return result
            # The policy may authorize the canonical time tool but not the
            # plugin (or plugin discovery may be unavailable). Never bypass
            # the plan: run_tool independently enforces tool eligibility,
            # action gates, and execution budget.
            result = await run_tool()
            if result is not None:
                return result
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

        # Search capabilities prefer the production web_search tool because it
        # carries the AuthorizedExecutionPlan and scoped runtime identity into
        # InternetCapabilityService. The plugin remains an authorized fallback.
        result = await run_tool()
        if result is not None:
            return result

        result = await run_plugin()
        if result is not None:
            return result

        target = tool_name or preferred_plugin or capability or "live capability"
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
        effective = (request.metadata or {}).get("clarification_effective_query")
        if isinstance(effective, str) and effective.strip():
            return effective.strip()
        for message in reversed(request.messages):
            if str(message.get("role") or "").lower() == "user":
                return str(message.get("content") or "").strip()
        return ""

    @staticmethod
    def _normalize_payload(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {"value": value}

    @staticmethod
    def _payload_succeeded(intent: str, payload: Dict[str, Any]) -> bool:
        if str(payload.get("status") or "").lower() in {"error", "failed"}:
            return False
        if payload.get("error"):
            return False

        if intent == "system.resources":
            return isinstance(payload.get("memory"), dict) and bool(payload["memory"].get("available"))

        if intent == "time.current":
            return any(
                payload.get(key) not in (None, "")
                for key in ("value", "formatted", "time", "iso")
            )

        if intent == "search.general":
            extracted = payload.get("extractedData")
            if isinstance(extracted, dict) and any(
                value not in (None, "", [], {})
                for value in extracted.values()
            ):
                return True
            # An empty source object or a URL without article evidence must
            # not be represented to consumers as a successful live search.
            return any(
                isinstance(item, dict)
                and str(item.get("url") or "").startswith(("https://", "http://"))
                and bool(str(
                    item.get("snippet")
                    or item.get("content")
                    or ""
                ).strip())
                for key in ("results", "sources")
                for item in (payload.get(key) or [])
            )

        if intent == "search.weather":
            return bool(DirectCapabilityExecutor._weather_observation(payload))

        return bool(payload)

    @staticmethod
    def _weather_observation(payload: Dict[str, Any]) -> Optional[str]:
        """Only meteorological measurements count as live weather evidence.

        Generic search excerpts, city encyclopedias and organization names
        cannot establish current weather. Preserve provider provenance in the
        surrounding capability result rather than claiming a verified forecast.
        """
        fields = ("temperature", "temp", "temperature_c", "temperature_f",
                  "conditions", "condition", "humidity", "wind_speed",
                  "precipitation", "forecast", "high", "low")
        containers = [payload.get("extractedData"), payload.get("weather"),
                      payload.get("current"), payload.get("observation")]
        for candidate in containers:
            if not isinstance(candidate, dict):
                continue
            present = [
                f"{key}: {candidate[key]}"
                for key in fields
                if candidate.get(key) not in (None, "", [], {})
            ]
            if present and any(
                candidate.get(key) not in (None, "", [], {})
                for key in ("temperature", "temp", "temperature_c",
                            "temperature_f", "conditions", "condition",
                            "forecast")
            ):
                qualifiers = [
                    f"{key}: {candidate[key]}"
                    for key in ("location", "city", "observed_at", "timestamp",
                                "valid_time", "updated_at", "date")
                    if candidate.get(key) not in (None, "", [], {})
                ]
                return ", ".join((qualifiers + present)[:10])
        return None

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
        # Search adapters may return article records under "results" rather
        # than "sources". Preserve source provenance for response/UI consumers
        # without inventing URLs, timestamps, or synthetic citations.
        sources = [
            item for item in list(payload.get("sources") or []) if isinstance(item, dict)
        ]
        if intent == "search.general":
            seen_urls = {
                str(item.get("url") or "").strip()
                for item in sources
                if str(item.get("url") or "").strip()
            }
            for item in payload.get("results") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url.startswith(("http://", "https://")) or url in seen_urls:
                    continue
                if not str(item.get("snippet") or item.get("content") or "").strip():
                    continue
                sources.append(dict(item))
                seen_urls.add(url)
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
        denial = any(a.get("error") in {"not_in_authorized_plan", "execution_gate_denied"} for a in attempts)
        execution_failed = any(a.get("status") == "failed" for a in attempts)
        if execution_failed:
            message = "The live data provider failed or returned no usable result."
            next_action = "inspect_provider_attempts"
        elif denial:
            message = "The live capability was not authorized for this request."
            next_action = "inspect_authorized_execution_plan"
        else:
            message = "No executable live capability is configured for this request."
            next_action = "inspect_capability_registration"
        text = f"I couldn't retrieve live information: {message} Required capability: {capability_label}."
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
                "next_action": next_action,
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
    def _weather_query_with_location(
        query: str, metadata: Dict[str, Any]
    ) -> Optional[str]:
        """Resolve weather location without silently inferring private geography.

        Explicit place names in the user query take precedence over an
        authorized selected/profile location. If neither exists, the DIRECT
        executor asks one targeted question before making an internet call.
        """
        explicit = re.search(
            r"\b(?:weather(?:\s+like)?|forecast|temperature)"
            r"(?:\s+(?:today|tomorrow|tonight|right\s+now|this\s+(?:morning|afternoon|evening)))?"
            r"\s+(?:in|for|at)\s+"
            r"(?P<place>[A-Za-z][A-Za-z0-9 ,.'-]{0,110})",
            query,
            flags=re.IGNORECASE,
        )
        if not explicit:
            explicit = re.search(
                r"\b(?:in|for)\s+(?P<place>[A-Za-z][A-Za-z0-9 ,.'-]{0,110})"
                r"\s+(?:weather|forecast)\b",
                query,
                flags=re.IGNORECASE,
            )
        if explicit:
            place = explicit.group("place").strip(" ?!. ,")
            if place:
                return query

        context = dict(metadata or {})
        pending = context.get("pending_clarification")
        if isinstance(pending, dict) and pending.get("missing_requirement") == "weather_location":
            candidate = query.strip(" ?!. ,")
            if re.fullmatch(r"[A-Za-z][A-Za-z .,'-]{1,119}", candidate):
                return f"What's the weather in {candidate}?"
        location = context.get("weather_location")
        if not isinstance(location, str) or not location.strip():
            source = context.get("location_source")
            if source in {"user_selected", "user_profile", "device_with_consent"}:
                location = context.get("location") or context.get("city")
            else:
                location = None
        if isinstance(location, str):
            location = location.strip()
            if location and len(location) <= 120:
                return f"{query.rstrip(' ?!.')} in {location}?"
        return None

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
        resolved_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if intent == "time.current":
            is_date_query = bool(re.search(r"\bdate\b", query, re.IGNORECASE))
            location = self._extract_time_location(query)
            if location:
                return {
                    "mode": "world_time",
                    "query": location,
                    "context": dict(request.metadata or {}),
                }

            from ai_karen_engine.core.runtime.location_context import resolve_location
            selected_timezone = resolve_location(
                request.metadata, resolved_context, kind="time"
            )
            timezone_name = selected_timezone.value if selected_timezone else None
            params: Dict[str, Any] = {
                "mode": "date" if is_date_query else "time",
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
            r"^what\s+time\s+is\s+it(?:\s+right\s+now)?\s+(?:in|for)\s+(.+?)[?!.]*$",
            r"^what(?:'s|s|\s+is)\s+the\s+(?:current\s+)?time\s+(?:in|for)\s+(.+?)[?!.]*$",
            r"^(?:current\s+time|time\s+now)\s+(?:in|for)\s+(.+?)[?!.]*$",
            r"^timezone\s+(?:in|for|of)\s+(.+?)[?!.]*$",
            r"^time\s+in\s+(.+?)[?!.]*$",
            r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?tell\s+me\s+(?:what\s+time\s+it\s+is|what\s+time\s+is\s+it|the\s+(?:current\s+)?time)\s+(?:in|for)\s+(.+?)[?!.]*$",
        )
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                location = re.sub(
                    r"[,;:]?\s*right\s+now$",
                    "",
                    match.group(1),
                    flags=re.IGNORECASE,
                ).strip(" ,")
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
        if intent == "system.resources":
            requested = (
                "vram" if re.search(r"\bvram\b", query, re.I)
                else "disk" if re.search(r"\bdisk\b", query, re.I)
                else "memory"
            )
            metric = payload.get(requested)
            if not isinstance(metric, dict) or not metric.get("available"):
                return f"Current {requested.upper() if requested == 'vram' else requested} availability could not be measured."
            available = metric.get("available_bytes")
            total = metric.get("total_bytes")
            if not isinstance(available, (int, float)) or isinstance(available, bool):
                return "Resource snapshot did not report available capacity."
            remaining_gib = available / (1024 ** 3)
            if isinstance(total, (int, float)) and not isinstance(total, bool):
                return f"Available {requested}: {remaining_gib:.2f} GiB of {total / (1024 ** 3):.2f} GiB."
            return f"Available {requested}: {remaining_gib:.2f} GiB."
        if intent == "time.current":
            if payload.get("mode") == "date":
                date_value = payload.get("date") or payload.get("value")
                if date_value:
                    timezone_label = payload.get("resolved_timezone") or payload.get("timezone")
                    if timezone_label:
                        return f"The current date in {timezone_label} is {date_value}."
                    return f"The current date is {date_value}."
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

        if intent == "search.weather":
            observation = self._weather_observation(payload)
            return (
                observation
                if observation
                else "Live weather measurements are unavailable from the configured providers."
            )

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
                for item in list(
                    payload.get("results") or payload.get("sources") or []
                )
                if isinstance(item, dict)
            ]
            passages = []
            for item in results:
                if len(passages) >= 3:
                    break
                excerpt = str(item.get("snippet") or item.get("content") or "").strip()[:400]
                source_url = str(item.get("url") or "").strip()
                if not excerpt or not source_url.startswith(("https://", "http://")):
                    continue
                headline = str(item.get("title") or item.get("headline") or "").strip()[:200]
                published = str(
                    item.get("published_at")
                    or item.get("published")
                    or item.get("publication_date")
                    or item.get("publishedAt")
                    or ""
                ).strip()[:80]
                details = []
                if headline:
                    details.append(f"Headline: {headline}")
                if published:
                    details.append(f"Published (provider-reported): {published}")
                details.extend((excerpt, f"Source: {source_url}"))
                passages.append("\n".join(details))
            if passages:
                prefix = (
                    "Live weather evidence (retrieved excerpts, not a generated forecast):"
                    if intent == "search.weather"
                    else "Retrieved evidence (not a synthesized answer):"
                )
                return prefix + "\n\n" + "\n\n".join(passages)

            # Weather tool measurements can be useful even when the provider
            # supplies no page URL; do not discard legitimate weather data.
            if intent == "search.weather":
                measurements = [
                    str(item.get("snippet") or item.get("content") or "").strip()[:400]
                    for item in results[:3]
                    if item.get("snippet") or item.get("content")
                ]
                if measurements:
                    return "Weather information returned by the live capability (source URL unavailable):\n\n" + "\n\n".join(measurements)

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

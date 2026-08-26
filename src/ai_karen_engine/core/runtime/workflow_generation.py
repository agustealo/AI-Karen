"""Runtime-owned model generation port for graph workflows.

LangGraph is allowed to assemble workflow-local context, but provider/model
selection, prompt assembly, provider execution, fallback semantics, and actual
provider/model provenance remain Runtime responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.model_runtime.runtime_contracts import (
    ProviderExecutionResult,
    ProviderRouteDecision,
)
from ai_karen_engine.core.runtime.prompt import get_prompt_runtime_service
from ai_karen_engine.core.runtime.provider_runtime import ProviderRuntime

logger = get_logger(__name__)


@dataclass(slots=True)
class WorkflowGenerationRequest:
    """Framework-neutral request from an authorized workflow stage."""

    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str]
    policy_decision_id: str
    messages: List[Dict[str, Any]]
    request_context: Dict[str, Any] = field(default_factory=dict)
    integrated_context: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    workflow_context: Dict[str, Any] = field(default_factory=dict)
    cortex_intent: Dict[str, Any] = field(default_factory=dict)
    authorized_plan: Dict[str, Any] = field(default_factory=dict)
    stream: bool = False


class WorkflowGenerationRuntime:
    """Single Runtime owner for model generation inside LangGraph workflows."""

    def __init__(self) -> None:
        self._router: Optional[Any] = None
        self._provider_runtime: Optional[ProviderRuntime] = None

    def _get_router(self) -> Any:
        if self._router is None:
            from ai_karen_engine.core.model_runtime.routing.llm_router_service import LLMRouter

            self._router = LLMRouter()
        return self._router

    def _get_provider_runtime(self) -> ProviderRuntime:
        if self._provider_runtime is None:
            router = self._get_router()
            self._provider_runtime = ProviderRuntime(router=router)
        return self._provider_runtime

    async def execute(
        self,
        request: WorkflowGenerationRequest,
    ) -> ProviderExecutionResult:
        """Assemble, route, and execute one authorized workflow generation."""

        self._validate_authorization(request)
        router = self._get_router()
        prompt_runtime = get_prompt_runtime_service()

        token_budget = int(
            request.request_context.get("token_budget")
            or request.request_context.get("max_input_tokens")
            or 4096
        )
        prompt_request = prompt_runtime.build_request_from_runtime_context(
            messages=list(request.messages),
            request_context=dict(request.request_context),
            integrated_context=dict(request.integrated_context),
            profile=dict(request.profile),
            workflow_context=dict(request.workflow_context),
            cortex_intent=dict(request.cortex_intent),
            token_budget=token_budget,
        )
        assembled_prompt = await prompt_runtime.assemble_prompt(prompt_request)

        from ai_karen_engine.core.model_runtime.routing.llm_router_service import ChatRequest

        preferred_provider = self._preferred_provider(request)
        preferred_model = self._preferred_model(request)
        user_preferences = self._provider_preferences(
            request,
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
        )
        intent = str(request.cortex_intent.get("primary_intent") or "general.chat")
        subtype = request.cortex_intent.get("subtype")
        last_message = str(request.messages[-1].get("content") or "") if request.messages else ""

        chat_request = ChatRequest(
            message=last_message,
            intent=intent,
            subtype=str(subtype) if subtype is not None else None,
            context={
                "messages": assembled_prompt.messages,
                "prompt_text": prompt_runtime.render_text_prompt(assembled_prompt.messages),
                "prompt_hash": assembled_prompt.prompt_hash,
                "prompt_metadata": assembled_prompt.metadata,
                "truncation_events": [
                    {
                        "section": event.section,
                        "reason": event.reason,
                        "items_removed": event.items_removed,
                    }
                    for event in assembled_prompt.truncation_events
                ],
                "workflow": dict(request.workflow_context),
            },
            user_preferences=user_preferences,
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
            conversation_id=request.conversation_id,
            stream=request.stream,
            max_tokens=request.request_context.get("max_tokens"),
            temperature=request.request_context.get("temperature"),
            requires_chat_capable_model=True,
        )

        decision = await router.select_provider(
            chat_request,
            user_preferences=user_preferences,
        )
        if decision is None:
            return self._unavailable_result(
                request,
                reason="provider_router_returned_no_decision",
                requested_provider=preferred_provider,
                requested_model=preferred_model,
            )

        decision = replace(
            decision,
            correlation_id=request.correlation_id,
            policy_decision_id=request.policy_decision_id,
        )
        policy_error = self._validate_route_against_plan(request, decision)
        if policy_error:
            return self._unavailable_result(
                request,
                reason=policy_error,
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
            )

        result = await self._get_provider_runtime().execute_chat(
            decision,
            chat_request,
            user_preferences=user_preferences,
        )

        if result.response_source == "emergency_static":
            return replace(
                result,
                text="",
                actual_provider=None,
                actual_model=None,
                runtime_engine=None,
                response_source="model_unavailable",
                degraded_mode=True,
                fallback_level=max(99, int(result.fallback_level or 0)),
                degradation_type=result.degradation_type or "fallback_exhausted",
                degradation_reason=(
                    result.degradation_reason
                    or "No authorized provider completed workflow generation."
                ),
            )
        return result

    @staticmethod
    def _validate_authorization(request: WorkflowGenerationRequest) -> None:
        if not request.tenant_id or request.tenant_id == "default":
            raise PermissionError("Workflow generation requires explicit tenant_id")
        if not request.policy_decision_id:
            raise PermissionError("Workflow generation requires policy_decision_id")
        if not isinstance(request.authorized_plan, dict) or not request.authorized_plan:
            raise PermissionError("Workflow generation requires AuthorizedExecutionPlan")
        plan_policy_id = str(request.authorized_plan.get("policy_decision_id") or "")
        if plan_policy_id != request.policy_decision_id:
            raise PermissionError(
                "Workflow generation policy_decision_id does not match authorization"
            )

    @staticmethod
    def _preferred_provider(request: WorkflowGenerationRequest) -> Optional[str]:
        value = (
            request.request_context.get("provider")
            or request.request_context.get("preferred_llm_provider")
        )
        return str(value) if value else None

    @staticmethod
    def _preferred_model(request: WorkflowGenerationRequest) -> Optional[str]:
        value = (
            request.request_context.get("model")
            or request.request_context.get("preferred_model")
        )
        return str(value) if value else None

    @staticmethod
    def _provider_preferences(
        request: WorkflowGenerationRequest,
        *,
        preferred_provider: Optional[str],
        preferred_model: Optional[str],
    ) -> Dict[str, Any]:
        preferences: Dict[str, Any] = {}
        raw = request.profile.get("provider_preferences")
        if isinstance(raw, dict):
            preferences.update(raw)
        if preferred_provider:
            preferences["preferred_llm_provider"] = preferred_provider
        if preferred_model:
            preferences["preferred_model"] = preferred_model
        return preferences

    @staticmethod
    def _validate_route_against_plan(
        request: WorkflowGenerationRequest,
        decision: ProviderRouteDecision,
    ) -> Optional[str]:
        constraints = request.authorized_plan.get("provider_constraints") or {}
        if not isinstance(constraints, dict):
            return "invalid_provider_constraints"

        selected_provider = str(decision.selected_provider or "")
        selected_model = str(decision.selected_model or "")

        allowed_providers = constraints.get("allowed_providers")
        if isinstance(allowed_providers, list) and allowed_providers:
            allowed = {str(item) for item in allowed_providers}
            if selected_provider not in allowed:
                return "provider_not_authorized_by_runtime_policy"

        forbidden_providers = constraints.get("forbidden_providers")
        if isinstance(forbidden_providers, list):
            forbidden = {str(item) for item in forbidden_providers}
            if selected_provider in forbidden:
                return "provider_forbidden_by_runtime_policy"

        allowed_models = constraints.get("allowed_models")
        if isinstance(allowed_models, list) and allowed_models and selected_model:
            allowed = {str(item) for item in allowed_models}
            if selected_model not in allowed:
                return "model_not_authorized_by_runtime_policy"

        return None

    @staticmethod
    def _unavailable_result(
        request: WorkflowGenerationRequest,
        *,
        reason: str,
        requested_provider: Optional[str] = None,
        requested_model: Optional[str] = None,
        selected_provider: Optional[str] = None,
        selected_model: Optional[str] = None,
    ) -> ProviderExecutionResult:
        logger.warning(
            "workflow_generation.unavailable",
            extra={
                "correlation_id": request.correlation_id,
                "tenant_id": request.tenant_id,
                "policy_decision_id": request.policy_decision_id,
                "reason": reason,
            },
        )
        return ProviderExecutionResult(
            text="",
            requested_provider=requested_provider,
            requested_model=requested_model,
            selected_provider=selected_provider,
            selected_model=selected_model,
            actual_provider=None,
            actual_model=None,
            runtime_engine=None,
            response_source="model_unavailable",
            fallback_level=99,
            degraded_mode=True,
            degradation_type="provider_unavailable",
            degradation_reason=reason,
            correlation_id=request.correlation_id,
            provider_attempts=[],
            metadata={
                "policy_decision_id": request.policy_decision_id,
                "response_source": "model_unavailable",
            },
        )


_runtime: Optional[WorkflowGenerationRuntime] = None


def get_workflow_generation_runtime() -> WorkflowGenerationRuntime:
    global _runtime
    if _runtime is None:
        _runtime = WorkflowGenerationRuntime()
    return _runtime


__all__ = [
    "WorkflowGenerationRequest",
    "WorkflowGenerationRuntime",
    "get_workflow_generation_runtime",
]

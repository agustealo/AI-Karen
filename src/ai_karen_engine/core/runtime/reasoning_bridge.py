from __future__ import annotations

"""Runtime-owned activation bridge for specialist reasoning strategies.

CORTEX decides reasoning modes and RuntimePolicy authorizes them. This module
resolves Runtime-owned dependencies for those already-authorized modes and
returns a ReasoningExecutor plus request metadata. Core reasoning strategies do
not discover providers, models, prompts, or policy on their own.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Sequence

from ai_karen_engine.core.reasoning.contracts import normalize_reasoning_modes
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudgetMeter,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.policy import ResponseStrategyPolicyProbe

if TYPE_CHECKING:
    from ai_karen_engine.core.model_runtime.governed_model_admission import GovernedToolModelAdmission
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.soft_reasoning_composition import (
        ComposedSoftReasoning,
    )


SOFT_EXPLORATION_MODE = "soft_exploration"


def get_runtime_soft_reasoning_composer() -> Any:
    """Resolve the canonical composer lazily, retaining the patchable bridge API."""
    from ai_karen_engine.core.runtime.soft_reasoning_composition import (
        get_runtime_soft_reasoning_composer as resolve_composer,
    )

    return resolve_composer()


class ReasoningActivationError(RuntimeError):
    """Raised when an authorized reasoning mode cannot be activated safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReasoningActivation:
    executor: ReasoningExecutor
    reasoning_modes: tuple[str, ...]
    request_metadata: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    # Host-owned accounting, never request or strategy diagnostic metadata.
    reserved_model_calls: Callable[[], int] | None = None


@dataclass(frozen=True, slots=True)
class VerificationAlternativeReadiness:
    """Diagnostic only: policy permission is not a runnable alternative."""

    source_decision_id: str
    source_policy_version: str
    alternative_policy_decision_id: str | None
    status: str
    reason_codes: tuple[str, ...]
    verifier_strategy_id: str | None = None
    verifier_strategy_version: str | None = None
    provider_health: str = "unknown"
    model_in_registered_inventory: bool | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "verification_alternative_readiness_v1",
            "source_decision_id": self.source_decision_id,
            "source_policy_version": self.source_policy_version,
            "alternative_policy_decision_id": self.alternative_policy_decision_id,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "verifier_strategy_id": self.verifier_strategy_id,
            "verifier_strategy_version": self.verifier_strategy_version,
            "provider_health": self.provider_health,
            "model_in_registered_inventory": self.model_in_registered_inventory,
            "execution_eligibility_established": False,
            "randomized_selection": False,
            "ope_eligible": False,
        }


class RuntimeReasoningBridge:
    """Compose runtime-specific strategies for an authorized reasoning plan."""

    def inspect_optional_verification_readiness(
        self,
        *,
        permission: ResponseStrategyPolicyProbe,
        decision: ExecutionDecision,
        preferred_provider: str | None,
        preferred_model: str | None,
        provider_registry: Any | None = None,
    ) -> VerificationAlternativeReadiness:
        """Read canonical capability and health evidence without executing.

        The chosen plan is NEVER replaced. Even a healthy provider and a
        registered verifier cannot prove that a complete verification answer
        ran or that both actions are interchangeable. This function therefore
        deliberately has no "ready" outcome and cannot unlock OPE.
        """
        source_id = permission.source_decision_id
        source_version = permission.source_policy_version
        alternate_id = permission.alternative_policy_decision_id

        permitted = (
            permission.status == "alternative_reasoning_mode_policy_permitted"
            and permission.policy_permitted_actions
            == ("respond_direct", "verify_then_respond")
            and permission.selected_action == "respond_direct"
            and bool(alternate_id)
            and permission.alternative_policy_version == source_version
            and source_id == decision.policy_decision_id
            and source_version == decision.policy_version
            and decision.topology == ExecutionTopology.DIRECT
            and not decision.reasoning_modes
            and not decision.requires_human_gate
            and not decision.tool_requirements
            and not decision.plugin_candidates
            and not decision.requires_agent_delegation
            and not decision.requires_parallel_execution
            and not decision.requires_resumability
            and not decision.workflow_id
            and getattr(decision.risk_level, "value", decision.risk_level)
            in {"low", "medium"}
        )
        if not permitted:
            return VerificationAlternativeReadiness(
                source_decision_id=source_id,
                source_policy_version=source_version,
                alternative_policy_decision_id=alternate_id,
                status="not_permitted",
                reason_codes=("alternative_policy_or_plan_not_authorized",),
            )

        reasons: list[str] = []
        blocked = False
        if (
            decision.max_model_calls < 2
            or decision.max_steps < 1
            or decision.time_budget_ms <= 0
            or decision.token_budget <= 0
        ):
            blocked = True
            reasons.append("insufficient_authorized_execution_budget")

        # Use the same actual default-strategy factory as activate(). Merely
        # declaring a mode in a request is not evidence of a loaded executor.
        # The default strategy factory is also used by activate(), but
        # importing it can require optional ML packages. An unavailable
        # dependency is a real blocker, never an empty/fabricated registry.
        # The optional diagnostic must not crash Main Quality or chat.
        try:
            from ai_karen_engine.core.reasoning.defaults import (
                get_default_strategies,
            )

            # Multiple strategies may legitimately handle verification.
            verifiers = [
                item for item in get_default_strategies()
                if item.strategy_id == "verify" and item.can_handle(["verification"])
            ]
        except ImportError:
            verifiers = []
            blocked = True
            reasons.append("verification_strategy_dependency_unavailable")
        verifier = verifiers[0] if len(verifiers) == 1 else None
        if verifier is None:
            blocked = True
            reasons.append("canonical_verification_strategy_unavailable")
        elif not verifier.supports_model_calls:
            # A deterministic verifier alone cannot generate the final reply.
            reasons.append("verification_strategy_nongenerative")

        provider_health = "unknown"
        model_registered: bool | None = None
        provider = (preferred_provider or "").strip()
        model = (preferred_model or "").strip()
        if (
            not provider or not model
            or provider.lower() == "auto" or model.lower() == "auto"
        ):
            reasons.append("model_selection_not_runtime_resolved")
        else:
            if provider_registry is None:
                from ai_karen_engine.core.model_runtime.provider_registry_service import (
                    get_provider_registry_service,
                )

                provider_registry = get_provider_registry_service()

            provider_id = provider_registry.canonicalize_provider_id(provider)
            if not provider_id or provider_id not in provider_registry.get_all_provider_names():
                blocked = True
                reasons.append("provider_not_registered")
            else:
                health = provider_registry.health_monitor.get_provider_health(provider_id)
                observed = getattr(health, "health_status", None)
                provider_health = str(getattr(observed, "value", observed or "unknown"))
                if provider_health in {"unavailable", "unhealthy"}:
                    blocked = True
                    reasons.append("provider_observed_unavailable")
                elif provider_health != "healthy" or health.last_checked_at is None:
                    reasons.append("provider_health_unverified")
                model_registered = provider_registry.is_model_available(
                    provider_id, model, healthy_only=False,
                )
                if not model_registered:
                    # Endpoint inventory may be dynamic. Missing registration
                    # is not proof that a requested model does not exist.
                    reasons.append("model_inventory_unverified")

        reasons.append("complete_alternative_execution_not_observed")
        return VerificationAlternativeReadiness(
            source_decision_id=source_id,
            source_policy_version=source_version,
            alternative_policy_decision_id=alternate_id,
            status="blocked" if blocked else "unverified",
            reason_codes=tuple(dict.fromkeys(reasons)),
            verifier_strategy_id=verifier.strategy_id if verifier else None,
            verifier_strategy_version=verifier.version if verifier else None,
            provider_health=provider_health,
            model_in_registered_inventory=model_registered,
        )

    def activate(
        self,
        *,
        objective: str,
        evidence: Sequence[str],
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        preferred_provider: str | None,
        preferred_model: str | None,
        authenticated_context: ChatExecutionContext | None = None,
        execution_meter: ExecutionBudgetMeter | None = None,
    ) -> ReasoningActivation:
        requested_modes = tuple(
            normalize_reasoning_modes(list(decision.reasoning_modes))
        )
        authorized_modes = tuple(normalize_reasoning_modes(list(plan.reasoning_modes)))

        if not requested_modes:
            raise ReasoningActivationError(
                "reasoning_mode_not_requested",
                "CORTEX did not request a reasoning mode; Runtime cannot invent one",
            )
        if not authorized_modes:
            raise ReasoningActivationError(
                "reasoning_mode_not_authorized",
                "RuntimePolicy did not authorize any reasoning mode",
            )

        unauthorized = sorted(set(requested_modes) - set(authorized_modes))
        if unauthorized:
            raise ReasoningActivationError(
                "reasoning_mode_not_authorized",
                "RuntimePolicy did not authorize reasoning mode(s): "
                + ",".join(unauthorized),
            )

        optional_strategies = []
        reserved_model_calls = None
        request_metadata: dict[str, Any] = {}
        runtime_metadata: dict[str, Any] = {
            "reasoning_modes": list(requested_modes),
            "reasoning_activation": "core_defaults",
        }

        if SOFT_EXPLORATION_MODE in requested_modes:
            admission = self._require_soft_admission(
                plan, authenticated_context, execution_meter,
            )
            # Fail before resolving a provider, loading weights or mutating a
            # shared tokenizer. The composer must receive the original grant.
            from ai_karen_engine.core.reasoning.soft_reasoning.exploration import SoftExplorationConfig

            required = SoftExplorationConfig.paper_2025().maximum_total_model_calls
            self._validate_soft_budget(required, admission)
            composed = self._compose_soft_reasoning(
                objective=objective,
                evidence=evidence,
                preferred_provider=preferred_provider,
                preferred_model=preferred_model,
                execution_admission=admission,
            )
            self._validate_soft_budget(composed.maximum_total_model_calls, admission)
            reserved_model_calls = composed.reserved_model_calls
            if not callable(reserved_model_calls):
                raise ReasoningActivationError(
                    "soft_reasoning_accounting_unavailable",
                    "Soft Reasoning requires host-owned attempt accounting",
                )
            optional_strategies.append(composed.strategy)
            request_metadata.update(
                {
                    "soft_reasoning_prompt": composed.prepared_prompt,
                    "soft_reasoning_prompt_version": composed.prompt_version,
                    "soft_reasoning_profile": composed.profile,
                }
            )
            runtime_metadata.update(
                {
                    "reasoning_activation": "runtime_composed",
                    "soft_reasoning_profile": composed.profile,
                    "soft_reasoning_provider": composed.provider_id,
                    "soft_reasoning_model": composed.model_id,
                    "soft_reasoning_runtime_engine": composed.runtime_engine,
                    "soft_reasoning_marker_token_id": composed.marker_token_id,
                    "soft_reasoning_maximum_total_model_calls": (
                        composed.maximum_total_model_calls
                    ),
                }
            )

        from ai_karen_engine.core.reasoning.defaults import (
            get_default_strategies,
        )
        strategies = get_default_strategies(optional_strategies=optional_strategies)
        if reserved_model_calls is not None and any(
            item.supports_model_calls and item not in optional_strategies for item in strategies
        ):
            raise ReasoningActivationError(
                "reasoning_model_accounting_conflict", "Mixed model accounting is not authorized",
            )
        return ReasoningActivation(
            executor=ReasoningExecutor(strategies=strategies),
            reasoning_modes=requested_modes,
            request_metadata=request_metadata,
            runtime_metadata=runtime_metadata,
            reserved_model_calls=reserved_model_calls,
        )

    @staticmethod
    def _compose_soft_reasoning(
        *,
        objective: str,
        evidence: Sequence[str],
        preferred_provider: str | None,
        preferred_model: str | None,
        execution_admission: GovernedToolModelAdmission,
    ) -> ComposedSoftReasoning:
        from ai_karen_engine.core.runtime.soft_reasoning_composition import (
            SoftReasoningCompositionUnavailable,
        )

        try:
            return get_runtime_soft_reasoning_composer().compose_paper_2025(
                objective=objective,
                evidence=evidence,
                preferred_provider=preferred_provider,
                preferred_model=preferred_model,
                execution_admission=execution_admission,
            )
        except SoftReasoningCompositionUnavailable as exc:
            raise ReasoningActivationError(
                "soft_reasoning_runtime_unavailable",
                str(exc),
            ) from exc

    @staticmethod
    def _require_soft_admission(
        plan: AuthorizedExecutionPlan,
        context: ChatExecutionContext | None,
        meter: ExecutionBudgetMeter | None,
    ) -> GovernedToolModelAdmission:
        from ai_karen_engine.core.model_runtime.governed_model_admission import GovernedToolModelAdmission
        from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

        if (
            not isinstance(context, ChatExecutionContext)
            or not isinstance(meter, ExecutionBudgetMeter)
            or context.original_runtime_model_plan(meter) is not plan
        ):
            raise ReasoningActivationError(
                "soft_reasoning_original_admission_required",
                "Soft Reasoning requires the original authenticated runtime admission",
            )
        admission = GovernedToolModelAdmission(
            plan=plan, meter=meter, user_id=context.user_id,
            tenant_id=context.tenant_id, session_id=context.session_id,
            policy_decision_id=plan.policy_decision_id, request_id=context.request_id,
            correlation_id=context.correlation_id, authenticated_context=context,
        )
        try:
            admission._require_scope()
        except PermissionError as exc:
            raise ReasoningActivationError(
                "soft_reasoning_original_admission_required",
                "Soft Reasoning requires the original authenticated runtime admission",
            ) from exc
        return admission

    @staticmethod
    def _validate_soft_budget(
        required: int,
        admission: GovernedToolModelAdmission,
    ) -> None:
        meter = admission.meter
        available = 0 if meter.exhausted else max(
            0, admission.plan.budget.max_model_calls - meter.model_calls,
        )
        if available < required:
            raise ReasoningActivationError(
                "soft_reasoning_model_budget_insufficient",
                "Strict Soft Reasoning requires a model-call budget of at least "
                f"{required}; RuntimePolicy authorized {available}",
            )


def get_runtime_reasoning_bridge() -> RuntimeReasoningBridge:
    return RuntimeReasoningBridge()


__all__ = [
    "ReasoningActivation",
    "ReasoningActivationError",
    "VerificationAlternativeReadiness",
    "RuntimeReasoningBridge",
    "SOFT_EXPLORATION_MODE",
    "get_runtime_reasoning_bridge",
]

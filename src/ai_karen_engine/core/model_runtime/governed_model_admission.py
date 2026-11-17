"""Core-owned request admission for model, tool and embedding transports.

This is a validation/charging contract, never a grant issuer. A trusted runtime
must supply the original authenticated ChatExecutionContext, RuntimePolicy
AuthorizedExecutionPlan and the exact original ExecutionBudgetMeter. SDKs,
prompts and facade dictionaries cannot issue permission or reset a budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.model_runtime.provider_execution import (
    provider_endpoint_requires_external_permission,
)


@dataclass(frozen=True, slots=True, repr=False)
class GovernedToolModelAdmission:
    """One source of truth for SDK and Core model-attempt scope and reservations."""

    plan: Any
    meter: Any
    user_id: str
    tenant_id: str
    session_id: str | None
    policy_decision_id: str
    request_id: str
    correlation_id: str
    authenticated_context: Any = None

    def _require_scope(self, *, external: bool = False) -> None:
        from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan,
            ExecutionBudgetMeter,
        )

        context = self.authenticated_context
        valid = (
            isinstance(self.plan, AuthorizedExecutionPlan)
            and isinstance(self.meter, ExecutionBudgetMeter)
            and isinstance(context, ChatExecutionContext)
            and bool(self.plan.policy_decision_id)
            and self.plan.policy_decision_id == self.policy_decision_id
            and self.meter.budget is self.plan.budget
            and bool(self.user_id)
            and bool(self.tenant_id)
            and bool(self.request_id)
            and bool(self.correlation_id)
            and context.user_id == self.user_id
            and context.tenant_id == self.tenant_id
            and context.session_id == self.session_id
            and context.request_id == self.request_id
            and context.correlation_id == self.correlation_id
            and self.plan.matches_execution_scope(
                user_id=self.user_id,
                tenant_id=self.tenant_id,
                session_id=self.session_id,
                policy_decision_id=self.policy_decision_id,
            )
        )
        if not valid:
            raise PermissionError(
                "governed_external_model_execution_denied"
                if external else "governed_model_scope_or_budget_invalid"
            )
        try:
            context.require_authenticated_user()
        except (PermissionError, ValueError, TypeError) as exc:
            raise PermissionError(
                "governed_external_model_execution_denied"
                if external else "governed_model_scope_or_budget_invalid"
            ) from exc

    def _require_constraints(self, endpoint: ProviderEndpoint, model: str | None, *, external: bool) -> None:
        if not isinstance(endpoint, ProviderEndpoint) or not endpoint.enabled:
            raise PermissionError("governed_model_endpoint_not_eligible")
        constraints = self.plan.provider_constraints
        if not isinstance(constraints, dict):
            raise PermissionError("governed_model_provider_constraints_invalid")
        required = constraints.get("provider")
        eligible = constraints.get("eligible_providers")
        forbidden = constraints.get("forbidden_providers")
        if required and required != endpoint.provider_id:
            raise PermissionError("governed_model_provider_not_authorized")
        if eligible is not None:
            if not isinstance(eligible, (list, tuple, set)) or not all(
                isinstance(item, str) and item for item in eligible
            ):
                raise PermissionError("governed_model_provider_constraints_invalid")
            if eligible and endpoint.provider_id not in eligible:
                raise PermissionError("governed_model_provider_not_authorized")
        if forbidden is not None:
            if not isinstance(forbidden, (list, tuple, set)) or not all(
                isinstance(item, str) and item for item in forbidden
            ):
                raise PermissionError("governed_model_provider_constraints_invalid")
            if endpoint.provider_id in forbidden:
                raise PermissionError("governed_model_provider_not_authorized")
        if external and (constraints.get("local_only") is True or constraints.get("external_allowed") is False):
            raise PermissionError("governed_external_model_execution_denied")
        if model is not None:
            expected = constraints.get("model")
            allowed = constraints.get("allowed_models")
            if expected and expected != model:
                raise PermissionError("governed_model_identity_not_authorized")
            if allowed is not None:
                if not isinstance(allowed, (list, tuple, set)) or not all(
                    isinstance(item, str) and item for item in allowed
                ) or model not in allowed:
                    raise PermissionError("governed_model_identity_not_authorized")

    async def reserve_transport(self, endpoint: ProviderEndpoint, *, model: str | None = None) -> None:
        """Validate first; charge exactly one actual model attempt on original meter."""
        if not isinstance(endpoint, ProviderEndpoint):
            raise PermissionError("governed_model_endpoint_not_eligible")
        external = provider_endpoint_requires_external_permission(endpoint)
        self._require_scope(external=external)
        self._require_constraints(endpoint, model, external=external)
        if external:
            from ai_karen_engine.core.expression.settings import get_expression_settings
            from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer
            if not RuntimePolicyEnforcer.authorize_external_provider_execution(
                context=self.authenticated_context,
                plan=self.plan,
                expression_policies=get_expression_settings().policies,
            ):
                raise PermissionError("governed_external_model_execution_denied")
        if not await self.meter.reserve_model_execution(external=external):
            raise RuntimeError("governed_model_execution_budget_exhausted")

    async def reserve_local_embedding(self, *, model: str) -> None:
        """Charge a real local embedding attempt, never a synthetic fallback."""
        self._require_scope()
        if not isinstance(model, str) or not model or model == "auto":
            raise PermissionError("governed_embedding_model_identity_required")
        # An independently loaded local embedding model never gets a cloud grant.
        # A policy-constrained provider cannot be replaced with this local engine.
        constraints = self.plan.provider_constraints
        if not isinstance(constraints, dict):
            raise PermissionError("governed_model_provider_constraints_invalid")
        if constraints.get("provider") not in (None, "", "builtin_transformers"):
            raise PermissionError("governed_embedding_provider_not_authorized")
        allowed = constraints.get("allowed_models")
        expected = constraints.get("model")
        if expected and expected != model:
            raise PermissionError("governed_model_identity_not_authorized")
        if allowed is not None:
            if not isinstance(allowed, (list, tuple, set)) or model not in allowed:
                raise PermissionError("governed_model_identity_not_authorized")
        if not await self.meter.reserve_model_execution(external=False):
            raise RuntimeError("governed_model_execution_budget_exhausted")

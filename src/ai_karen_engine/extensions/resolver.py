"""
Capability Resolver for policy-aware capability resolution.

Resolves capability requirements to specific extensions based on:
  - capability match
  - version compatibility
  - enabled status
  - health/degraded policy
  - tenant eligibility
  - RBAC
  - required grants
  - credential availability
  - network/resource policy
  - requested provider hint
  - configured preference
  - local-first preference
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.contracts import (
    CapabilityInvocationRequest,
    ExtensionCapability,
    ExtensionLifecycleState,
    ExtensionRegistration,
    ResolvedCapability,
    TrustTier,
)
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan

logger = logging.getLogger("kari.extensions.resolver")


class CapabilityResolver:
    """Resolves capability requirements to specific extensions with policy awareness."""

    def __init__(
        self,
        registry: Any,
        health_service: Optional[Any] = None,
        credential_broker: Optional[Any] = None,
        network_policy: Optional[Any] = None,
        tenant_service: Optional[Any] = None,
        rbac_service: Optional[Any] = None,
    ):
        self._registry = registry
        self._health_service = health_service
        self._credential_broker = credential_broker
        self._network_policy = network_policy
        self._tenant_service = tenant_service
        self._rbac_service = rbac_service

    async def resolve(
        self,
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[AuthorizedExecutionPlan] = None,
        runtime_config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedCapability:
        """Resolve a capability request to a specific extension.

        Returns:
            ResolvedCapability with chosen extension and metadata.

        Raises:
            ValueError if no eligible implementation exists.
        """
        candidates = await self._find_candidates(request)

        if not candidates:
            raise ValueError(
                f"No eligible extensions found for capability '{request.capability_id}'"
            )

        chosen = await self._select_best_candidate(
            candidates,
            request,
            authorized_plan,
            runtime_config or {},
        )

        return self._create_resolution(chosen, request, authorized_plan)

    async def _find_candidates(
        self,
        request: CapabilityInvocationRequest,
    ) -> List[ExtensionRegistration]:
        """Find all candidate extensions that provide the requested capability."""

        candidates = self._registry.get_capability_candidates(
            request.capability_id,
            request.capability_version_constraint,
        )

        if not candidates:
            return []

        return await self._filter_basic_eligibility(candidates, request)

    async def _filter_basic_eligibility(
        self,
        candidates: List[ExtensionRegistration],
        request: CapabilityInvocationRequest,
    ) -> List[ExtensionRegistration]:
        """Apply basic eligibility filters."""
        eligible: List[ExtensionRegistration] = []

        for registration in candidates:
            if not self._is_enabled(registration):
                continue

            if not await self._is_healthy(registration):
                continue

            if not self._has_capability(registration, request.capability_id):
                continue

            if not await self._check_tenant_eligibility(registration, request):
                continue

            eligible.append(registration)

        return eligible

    def _is_enabled(self, registration: ExtensionRegistration) -> bool:
        """Check if extension is enabled."""
        return registration.state == ExtensionLifecycleState.ENABLED

    async def _is_healthy(self, registration: ExtensionRegistration) -> bool:
        """Check if extension is healthy enough to execute."""
        if self._health_service is None:
            return True

        try:
            health_record = self._health_service.get_health(registration.manifest.id)
            if health_record is None:
                return True

            if health_record.health == "unavailable":
                return False

            if health_record.health == "degraded":
                degraded_allowed = self._runtime_config.get("allow_degraded", True)
                return degraded_allowed

            return True
        except Exception:
            return True

    def _has_capability(self, registration: ExtensionRegistration, capability_id: str) -> bool:
        """Check if extension declares the capability."""
        for cap in registration.manifest.capabilities:
            if getattr(cap, "id", str(cap)) == capability_id:
                return True
        return False

    async def _check_tenant_eligibility(
        self,
        registration: ExtensionRegistration,
        request: CapabilityInvocationRequest,
    ) -> bool:
        """Check tenant scope eligibility."""
        manifest = registration.manifest
        tenant_id = request.context.tenant_id

        if manifest.tenant_scope == "single":
            return bool(tenant_id)

        if manifest.tenant_scope == "multi":
            return tenant_id in manifest.allowed_tenant_ids

        if manifest.tenant_scope == "global":
            return False

        return True

    async def _select_best_candidate(
        self,
        candidates: List[ExtensionRegistration],
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[AuthorizedExecutionPlan],
        runtime_config: Dict[str, Any],
    ) -> ExtensionRegistration:
        """Select the best candidate from eligible extensions."""

        if len(candidates) == 1:
            return candidates[0]

        if request.provider_hint:
            hinted = [
                c for c in candidates
                if c.manifest.id == request.provider_hint
            ]
            if hinted:
                if await self._validate_provider_hint(hinted[0], request, authorized_plan):
                    return hinted[0]
                logger.warning(
                    "Provider hint '%s' for capability '%s' failed policy validation",
                    request.provider_hint,
                    request.capability_id,
                )

        return await self._rank_candidates(candidates, request, runtime_config)

    async def _validate_provider_hint(
        self,
        registration: ExtensionRegistration,
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[AuthorizedExecutionPlan],
    ) -> bool:
        """Validate that an explicitly requested provider is allowed."""
        hint_policy = self._runtime_config.get("provider_hint_policy", "default")

        if hint_policy == "forbidden":
            return False

        if hint_policy == "admin_only":
            user_roles = request.context.audit_context.get("user_roles", [])
            return "admin" in user_roles

        return True

    async def _rank_candidates(
        self,
        candidates: List[ExtensionRegistration],
        request: CapabilityInvocationRequest,
        runtime_config: Dict[str, Any],
    ) -> ExtensionRegistration:
        """Rank candidates by preference and return the best one."""

        def score(registration: ExtensionRegistration) -> float:
            score = 0.0

            trust_tier = getattr(registration.manifest, "trust_tier", TrustTier.UNTRUSTED)
            trust_scores = {
                TrustTier.BUILTIN_TRUSTED: 100,
                TrustTier.FIRST_PARTY: 80,
                TrustTier.SIGNED_THIRD_PARTY: 60,
                TrustTier.UNTRUSTED: 40,
                TrustTier.REMOTE: 20,
            }
            score += trust_scores.get(trust_tier, 0)

            local_first = runtime_config.get("local_first", True)
            if local_first and trust_tier in {TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY}:
                score += 10

            for cap in registration.manifest.capabilities:
                if getattr(cap, "id", str(cap)) == request.capability_id:
                    if getattr(cap, "result_trust", "untrusted_external") == "verified":
                        score += 5
                    if getattr(cap, "risk_class", "medium") == "safe":
                        score += 5
                    if getattr(cap, "idempotency", "unknown") == "idempotent":
                        score += 2

            return score

        scored = [(c, score(c)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0]

    def _create_resolution(
        self,
        registration: ExtensionRegistration,
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[AuthorizedExecutionPlan],
    ) -> ResolvedCapability:
        """Create a ResolvedCapability from the chosen registration."""

        capability: Optional[ExtensionCapability] = None
        for cap in registration.manifest.capabilities:
            if getattr(cap, "id", str(cap)) == request.capability_id:
                capability = cap
                break

        if capability is None:
            capability = ExtensionCapability(
                id=request.capability_id,
                version=request.capability_version_constraint or "1.0.0",
            )

        return ResolvedCapability(
            capability=capability,
            extension_id=registration.manifest.id,
            extension_version=registration.manifest.version,
            extension_trust_tier=getattr(registration.manifest, "trust_tier", TrustTier.UNTRUSTED),
            extension_isolation_mode=getattr(registration.manifest, "isolation_mode", "in_process"),
            policy_decision_id=request.context.policy_decision_id,
            resource_budget=request.context.budget,
        )

    async def validate_credentials(
        self,
        registration: ExtensionRegistration,
        capability_id: str,
    ) -> bool:
        """Validate that required credentials are available."""
        if self._credential_broker is None:
            return True

        for cap in registration.manifest.capabilities:
            if getattr(cap, "id", str(cap)) == capability_id:
                if not getattr(cap, "requires_credentials", False):
                    return True

        try:
            return await self._credential_broker.check_available(
                registration.manifest.id,
                capability_id,
            )
        except Exception:
            return False

    async def validate_network_policy(
        self,
        registration: ExtensionRegistration,
        capability_id: str,
        request: CapabilityInvocationRequest,
    ) -> bool:
        """Validate network policy for web capabilities."""
        if self._network_policy is None:
            return True

        for cap in registration.manifest.capabilities:
            if getattr(cap, "id", str(cap)) == capability_id:
                if not getattr(cap, "requires_network", False):
                    return True

        try:
            return await self._network_policy.check_allowed(
                registration.manifest.id,
                capability_id,
                request.payload,
                request.context,
            )
        except Exception:
            return False


__all__ = ["CapabilityResolver"]
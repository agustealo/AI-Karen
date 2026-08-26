"""
Canonical extension execution service.

This is the ONLY invocation path for extensions.

Execution must verify:
  1. capability resolved to extension
  2. correct version
  3. extension enabled
  4. healthy enough to execute
  5. requested capability declared
  6. extension is in AuthorizedExecutionPlan.allowed_plugins
  7. permission requirements satisfied
  8. RBAC satisfied
  9. tenant scope satisfied
  10. input schema valid
  11. ActionExecutionGate approves side effects
  12. budget available
  13. implementation resolves successfully
  14. timeout enforced
  15. output schema valid
  16. audit event emitted
  17. provenance and trust metadata attached
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Mapping

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    ActionExecutionGatePort,
    CapabilityInvocationRequest,
    DataClassification,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExecutionBudget,
    ExecutionIsolationMode,
    ResponseSource,
    ResultTrust,
    SideEffectLevel,
    TenantScope,
    TrustTier,
)
from ai_karen_engine.extensions.errors import (
    ExtensionCredentialDeniedError,
    ExtensionDisabledError,
    ExtensionError,
    ExtensionExecutionEngineError,
    ExtensionFilesystemDeniedError,
    ExtensionHumanGateRequiredError,
    ExtensionIsolationPolicyViolationError,
    ExtensionNetworkDeniedError,
    ExtensionNotFoundError,
    ExtensionNotRegisteredError,
    ExtensionPermissionError,
    ExtensionPolicyDeniedError,
    ExtensionPromptContractDeniedError,
    ExtensionSchemaError,
    ExtensionTenantDeniedError,
    ExtensionTimeoutClampedError,
    ExtensionTimeoutError,
)

logger = logging.getLogger("kari.extensions.executor")

_AUDIT_EVENT_TAXONOMY = {
    "resolution.started": "extension.resolution.started",
    "resolution.completed": "extension.resolution.completed",
    "policy.denied": "extension.policy.denied",
    "execution.started": "extension.execution.started",
    "execution.completed": "extension.execution.completed",
    "execution.failed": "extension.execution.failed",
    "execution.timeout": "extension.execution.timeout",
    "execution.cancelled": "extension.execution.cancelled",
    "schema.rejected": "extension.schema.rejected",
}


class ExtensionExecutionService:
    """Canonical extension execution service.

    Never calls plugins directly without passing through the full gate chain.
    """

    def __init__(
        self,
        registry: Any = None,
        lifecycle: Any = None,
        schema_validator: Any = None,
        audit_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        policy_resolver: Optional[Any] = None,
        capability_resolver: Optional[Any] = None,
        gate_port: Optional[ActionExecutionGatePort] = None,
        network_policy: Optional[Any] = None,
    ):
        self._registry = registry
        self._lifecycle = lifecycle
        self._schema_validator = schema_validator or _DefaultSchemaValidator()
        self._audit_sink = audit_sink
        self._policy_resolver = policy_resolver
        self._capability_resolver = capability_resolver
        self._gate_port = gate_port
        self._network_policy = network_policy
        self._max_timeout_ms = 30000
        self._active: Dict[str, asyncio.Task] = {}

    async def execute_capability(
        self,
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[Dict[str, Any]] = None,
    ) -> ExtensionExecutionResult:
        """Execute a capability request through full governance."""
        start = time.perf_counter()
        execution_id = str(uuid.uuid4())

        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["resolution.started"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id="unknown",
            plugin_version="unknown",
            capability=request.capability_id,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=TrustTier.UNTRUSTED.value,
            isolation_mode="unknown",
            side_effect_level="unknown",
            latency_ms=0.0,
            status="started",
            error_code=None,
        )

        if self._capability_resolver is None:
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["resolution.completed"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id="unknown",
                plugin_version="unknown",
                capability=request.capability_id,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=TrustTier.UNTRUSTED.value,
                isolation_mode="unknown",
                side_effect_level="unknown",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="failed",
                error_code="missing_resolver",
            )
            raise ExtensionError(
                "Capability resolver not configured",
                error_code="missing_resolver",
            )

        try:
            resolved = await self._capability_resolver.resolve(request, authorized_plan)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["resolution.completed"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id="unknown",
                plugin_version="unknown",
                capability=request.capability_id,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=TrustTier.UNTRUSTED.value,
                isolation_mode="unknown",
                side_effect_level="unknown",
                latency_ms=latency_ms,
                status="failed",
                error_code="resolution_failed",
            )
            return self._fail_capability(
                request,
                start,
                execution_id,
                "resolution_failed",
                str(exc),
            )

        ext_request = self._convert_to_ext_request(request, resolved)

        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["resolution.completed"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id=resolved.extension_id,
            plugin_version=resolved.extension_version,
            capability=request.capability_id,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=getattr(resolved, "extension_trust_tier", TrustTier.UNTRUSTED).value,
            isolation_mode=getattr(resolved, "extension_isolation_mode", "unknown"),
            side_effect_level=getattr(getattr(resolved, "capability", None), "side_effect_level", SideEffectLevel.NONE).value,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            status="completed",
            error_code=None,
        )

        result = await self.execute(ext_request)

        self._enrich_result_with_provenance(result, resolved)

        return result

    def _convert_to_ext_request(
        self,
        request: CapabilityInvocationRequest,
        resolved: Any,
    ) -> ExtensionExecutionRequest:
        """Convert capability invocation to extension execution request."""
        return ExtensionExecutionRequest(
            plugin_id=resolved.extension_id,
            capability=request.capability_id,
            payload=request.payload,
            context=request.context,
            authorized_plan=request.authorized_plan,
            timeout_override_ms=getattr(request, "timeout_override_ms", None),
            idempotency_key=getattr(request, "idempotency_key", None),
        )

    def _enrich_result_with_provenance(
        self,
        result: ExtensionExecutionResult,
        resolved: Any,
    ) -> None:
        """Add provenance metadata from resolved capability."""
        result.trust_tier = getattr(resolved, "extension_trust_tier", TrustTier.UNTRUSTED)

        if hasattr(resolved, "capability"):
            capability = resolved.capability
            result.result_trust = getattr(capability, "result_trust", ResultTrust.UNTRUSTED_EXTERNAL)
            result.data_classification = getattr(capability, "data_classification", DataClassification.PUBLIC)

    async def cancel(self, execution_id: str) -> bool:
        """Cancel a running execution by id."""
        task = self._active.pop(execution_id, None)
        if task is None:
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def execute(self, request: ExtensionExecutionRequest) -> ExtensionExecutionResult:
        """Execute an extension through the full governance gate chain."""
        start = time.perf_counter()
        plugin_id = request.plugin_id
        capability = request.capability
        execution_id = str(uuid.uuid4())

        try:
            registration = self._get_registration(plugin_id)
        except ExtensionError as exc:
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.failed"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version="unknown",
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=TrustTier.UNTRUSTED.value,
                isolation_mode="unknown",
                side_effect_level="unknown",
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="failed",
                error_code=exc.error_code,
            )
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                exc.error_code,
                str(exc),
                TrustTier.UNTRUSTED,
                ResultTrust.UNVERIFIED,
                DataClassification.PUBLIC,
            )

        manifest = registration.manifest
        context = request.context

        capability_obj = self._get_capability(manifest, capability)

        if capability_obj is not None:
            result_trust = getattr(capability_obj, "result_trust", ResultTrust.UNTRUSTED_EXTERNAL)
            data_classification = getattr(capability_obj, "data_classification", DataClassification.PUBLIC)
            trust_tier = getattr(manifest, "trust_tier", TrustTier.UNTRUSTED)
            side_effect_level = getattr(capability_obj, "side_effect_level", manifest.side_effect_level)
        else:
            result_trust = ResultTrust.UNTRUSTED_EXTERNAL
            data_classification = DataClassification.PUBLIC
            trust_tier = getattr(manifest, "trust_tier", TrustTier.UNTRUSTED)
            side_effect_level = manifest.side_effect_level

        if registration.state != ExtensionLifecycleState.ENABLED:
            error = ExtensionDisabledError(plugin_id)
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        health = self._get_health(plugin_id)
        if health != "healthy":
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "unavailable",
                f"Extension '{plugin_id}' is unavailable",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        declared_cap_ids = {cap.id for cap in manifest.capabilities}
        if capability not in declared_cap_ids:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "invalid_capability",
                f"Capability '{capability}' not declared by '{plugin_id}'",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        authorized_plan = request.authorized_plan or {}
        allowed_plugins = authorized_plan.get("allowed_plugins", [])
        if allowed_plugins and plugin_id not in allowed_plugins:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "not_authorized",
                f"Plugin '{plugin_id}' not in allowed_plugins",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        if not self._check_isolation_policy(manifest):
            error = ExtensionIsolationPolicyViolationError(plugin_id)
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        missing_perms = await self._check_permissions(manifest, context, authorized_plan, capability_obj)
        if missing_perms:
            error = ExtensionPermissionError(plugin_id, missing_perms)
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        rbac_ok = self._check_rbac(manifest, context, capability_obj)
        if not rbac_ok:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "rbac_denied",
                f"RBAC denied for '{plugin_id}'",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        tenant_ok = self._check_tenant(manifest, context)
        if not tenant_ok:
            error = ExtensionTenantDeniedError(plugin_id)
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        input_errors = self._schema_validator.validate_input(manifest, request.payload, capability_obj)
        if input_errors:
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["schema.rejected"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="rejected",
                error_code="invalid_input",
                detail="; ".join(input_errors),
            )
            error = ExtensionSchemaError(plugin_id, "input", "; ".join(input_errors))
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        if not self._check_budget(context):
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "budget_exhausted",
                "Execution budget exhausted",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        if side_effect_level != SideEffectLevel.NONE:
            if not self._check_network_policy(manifest, capability_obj, request):
                error = ExtensionNetworkDeniedError(plugin_id)
                return self._fail_with_provenance(
                    request,
                    start,
                    execution_id,
                    error.error_code,
                    str(error),
                    trust_tier,
                    result_trust,
                    data_classification,
                    manifest.version,
                )
            if not self._check_credential_policy(manifest, capability_obj):
                error = ExtensionCredentialDeniedError(plugin_id)
                return self._fail_with_provenance(
                    request,
                    start,
                    execution_id,
                    error.error_code,
                    str(error),
                    trust_tier,
                    result_trust,
                    data_classification,
                    manifest.version,
                )
            if not self._check_filesystem_policy(manifest, capability_obj, request):
                error = ExtensionFilesystemDeniedError(plugin_id)
                return self._fail_with_provenance(
                    request,
                    start,
                    execution_id,
                    error.error_code,
                    str(error),
                    trust_tier,
                    result_trust,
                    data_classification,
                    manifest.version,
                )

            gate_ok, decision_id, reason_codes, human_gate, approved_scope = (
                await self._check_gate(
                    principal=context.user_id,
                    tenant=context.tenant_id,
                    plugin_id=plugin_id,
                    capability_id=capability,
                    side_effect_level=side_effect_level.value,
                    resource_scope=context.resource_scope,
                    permissions=context.permissions,
                    risk_class=getattr(capability_obj, "risk_class", "medium") if capability_obj else "medium",
                    requires_network=bool(manifest.requires_network or (capability_obj and getattr(capability_obj, "requires_network", False))),
                    requires_filesystem=bool(manifest.requires_filesystem or (capability_obj and getattr(capability_obj, "requires_filesystem", False))),
                    requires_credentials=bool(manifest.requires_credentials or (capability_obj and getattr(capability_obj, "requires_credentials", False))),
                    requires_external_api=manifest.requires_external_api,
                    trust_tier=trust_tier.value,
                    isolation_mode=manifest.isolation_mode.value,
                )
            )
            if not gate_ok:
                self._audit(
                    event=_AUDIT_EVENT_TAXONOMY["policy.denied"],
                    request_id=request.context.request_id,
                    correlation_id=request.context.correlation_id,
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    plugin_id=plugin_id,
                    plugin_version=manifest.version,
                    capability=capability,
                    execution_id=execution_id,
                    policy_decision_id=decision_id,
                    trust_tier=trust_tier.value,
                    isolation_mode=manifest.isolation_mode.value,
                    side_effect_level=side_effect_level.value,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    status="denied",
                    error_code="policy_denied",
                    reason_codes=",".join(reason_codes),
                )
                error = ExtensionPolicyDeniedError(plugin_id, reason_codes)
                return self._fail_with_provenance(
                    request,
                    start,
                    execution_id,
                    error.error_code,
                    str(error),
                    trust_tier,
                    result_trust,
                    data_classification,
                    manifest.version,
                )

            if human_gate:
                error = ExtensionHumanGateRequiredError(plugin_id, decision_id)
                return self._fail_with_provenance(
                    request,
                    start,
                    execution_id,
                    error.error_code,
                    str(error),
                    trust_tier,
                    result_trust,
                    data_classification,
                    manifest.version,
                )

            request = ExtensionExecutionRequest(
                plugin_id=request.plugin_id,
                capability=request.capability,
                payload=request.payload,
                context=ExtensionExecutionContext(
                    request_id=context.request_id,
                    correlation_id=context.correlation_id,
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    conversation_id=context.conversation_id,
                    roles=context.roles,
                    permissions=context.permissions,
                    allowed_capabilities=context.allowed_capabilities,
                    policy_decision_id=decision_id,
                    resource_scope=approved_scope,
                    budget=context.budget,
                ),
                authorized_plan=request.authorized_plan,
                timeout_override_ms=getattr(request, "timeout_override_ms", None),
                idempotency_key=getattr(request, "idempotency_key", None),
            )

        if not self._check_prompt_contract(manifest, capability_obj, request.authorized_plan):
            error = ExtensionPromptContractDeniedError(plugin_id, "prompt contract mismatch")
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        handler = self._resolve_handler(registration)
        if handler is None:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "handler_missing",
                f"No executable handler for '{plugin_id}'",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        timeout_ms = self._get_timeout(request, manifest, capability_obj)
        clamped = False
        original_requested = getattr(request, "timeout_override_ms", None)
        if original_requested is not None and original_requested > timeout_ms:
            timeout_ms = self._max_timeout_ms if timeout_ms > self._max_timeout_ms else timeout_ms
            clamped = True

        if clamped:
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.timeout"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="clamped",
                error_code="timeout_clamped",
            )

        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["execution.started"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id=plugin_id,
            plugin_version=manifest.version,
            capability=capability,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=trust_tier.value,
            isolation_mode=manifest.isolation_mode.value,
            side_effect_level=side_effect_level.value,
            latency_ms=0.0,
            status="started",
            error_code=None,
        )

        task = asyncio.current_task()
        if task is not None:
            self._active[execution_id] = task

        try:
            raw_result = await asyncio.wait_for(self._invoke(handler, request), timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            error = ExtensionTimeoutError(plugin_id, timeout_ms)
            self._active.pop(execution_id, None)
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.timeout"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="timeout",
                error_code=error.error_code,
            )
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )
        except asyncio.CancelledError:
            self._active.pop(execution_id, None)
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.cancelled"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="cancelled",
                error_code="cancelled",
            )
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "cancelled",
                "Execution was cancelled",
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )
        except ExtensionError as exc:
            self._active.pop(execution_id, None)
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.failed"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="failed",
                error_code=exc.error_code,
            )
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                exc.error_code,
                str(exc),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )
        except Exception as exc:
            self._active.pop(execution_id, None)
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["execution.failed"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="failed",
                error_code="execution_error",
            )
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "execution_error",
                str(exc),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )
        finally:
            self._active.pop(execution_id, None)

        output_errors = self._schema_validator.validate_output(manifest, raw_result, capability_obj)
        if output_errors:
            self._audit(
                event=_AUDIT_EVENT_TAXONOMY["schema.rejected"],
                request_id=request.context.request_id,
                correlation_id=request.context.correlation_id,
                user_id=request.context.user_id,
                tenant_id=request.context.tenant_id,
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability=capability,
                execution_id=execution_id,
                policy_decision_id=request.context.policy_decision_id,
                trust_tier=trust_tier.value,
                isolation_mode=manifest.isolation_mode.value,
                side_effect_level=side_effect_level.value,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                status="rejected",
                error_code="invalid_output",
                detail="; ".join(output_errors),
            )
            error = ExtensionSchemaError(plugin_id, "output", "; ".join(output_errors))
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
                manifest.version,
            )

        latency_ms = (time.perf_counter() - start) * 1000.0

        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["execution.completed"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id=plugin_id,
            plugin_version=manifest.version,
            capability=capability,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=trust_tier.value,
            isolation_mode=manifest.isolation_mode.value,
            side_effect_level=side_effect_level.value,
            latency_ms=latency_ms,
            status="success",
            error_code=None,
            side_effects=self._infer_side_effects(manifest, capability_obj),
            permission_set=self._get_required_permissions(manifest, capability_obj),
        )

        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id=plugin_id,
            plugin_version=manifest.version,
            capability=capability,
            source=ResponseSource.PLUGIN,
            payload=raw_result,
            latency_ms=latency_ms,
            status="success",
            side_effects=self._infer_side_effects(manifest, capability_obj),
            permission_set=list(self._get_required_permissions(manifest, capability_obj)),
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            execution_id=execution_id,
            trust_tier=trust_tier,
            result_trust=result_trust,
            data_classification=data_classification,
            backend=manifest.metadata.get("backend"),
            backend_version=manifest.metadata.get("backend_version"),
            requested_url=None,
            final_url=None,
            canonical_url=None,
            fetched_at=None,
            status_code=None,
            content_type=None,
            content_hash=None,
            title=None,
            crawl_depth=None,
            parent_url=None,
            redirect_chain=[],
            extraction_method=None,
            warnings=[],
            raw_artifact_ref=None,
        )

    def _get_capability(self, manifest: ExtensionManifest, capability_id: str) -> Optional[ExtensionCapability]:
        """Get the capability object from manifest."""
        for cap in manifest.capabilities:
            if cap.id == capability_id:
                return cap
        return None

    def _get_required_permissions(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> List[str]:
        """Get required permissions as manifest UNION capability."""
        perms = set(manifest.required_permissions or [])
        if capability:
            perms.update(capability.required_permissions or [])
        return sorted(perms)

    def _get_required_roles(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> List[str]:
        """Get required roles as manifest UNION capability."""
        roles = set(manifest.required_roles or [])
        if capability:
            roles.update(capability.required_roles or [])
        return sorted(roles)

    def _get_timeout(self, request: ExtensionExecutionRequest, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> int:
        """Get effective timeout as min(policy maximum, manifest maximum, capability maximum, request override).

        Request override may only reduce the ceiling.
        """
        caps = [
            self._max_timeout_ms,
            manifest.timeout_ms,
        ]
        if capability and hasattr(capability, "retry_policy"):
            caps.append(capability.retry_policy.get("timeout_ms", manifest.timeout_ms))

        ceiling = min(caps)
        override = getattr(request, "timeout_override_ms", None)
        if override is not None:
            if override > ceiling:
                return ceiling
            return override
        return ceiling

    def _fail_with_provenance(
        self,
        request: ExtensionExecutionRequest,
        start: float,
        execution_id: str,
        error_code: str,
        detail: str,
        trust_tier: TrustTier,
        result_trust: ResultTrust,
        data_classification: DataClassification,
        plugin_version: str = "unknown",
    ) -> ExtensionExecutionResult:
        """Create failure result with provenance metadata."""
        latency_ms = (time.perf_counter() - start) * 1000.0
        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["execution.failed"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id=request.plugin_id,
            plugin_version=plugin_version,
            capability=request.capability,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=trust_tier.value,
            isolation_mode="unknown",
            side_effect_level="unknown",
            latency_ms=latency_ms,
            status="failed",
            error_code=error_code,
            detail=detail,
        )
        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id=request.plugin_id,
            plugin_version=plugin_version,
            capability=request.capability,
            source=ResponseSource.UNAVAILABLE,
            payload=None,
            latency_ms=latency_ms,
            status="failed",
            error_code=error_code,
            error_detail=detail,
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            execution_id=execution_id,
            trust_tier=trust_tier,
            result_trust=result_trust,
            data_classification=data_classification,
        )

    def _fail_capability(
        self,
        request: CapabilityInvocationRequest,
        start: float,
        execution_id: str,
        error_code: str,
        detail: str,
    ) -> ExtensionExecutionResult:
        """Create failure result for capability resolution errors."""
        latency_ms = (time.perf_counter() - start) * 1000.0
        self._audit(
            event=_AUDIT_EVENT_TAXONOMY["resolution.completed"],
            request_id=request.context.request_id,
            correlation_id=request.context.correlation_id,
            user_id=request.context.user_id,
            tenant_id=request.context.tenant_id,
            plugin_id="unknown",
            plugin_version="unknown",
            capability=request.capability_id,
            execution_id=execution_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=TrustTier.UNTRUSTED.value,
            isolation_mode="unknown",
            side_effect_level="unknown",
            latency_ms=latency_ms,
            status="failed",
            error_code=error_code,
            detail=detail,
        )
        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id="unknown",
            plugin_version="unknown",
            capability=request.capability_id,
            source=ResponseSource.UNAVAILABLE,
            payload=None,
            latency_ms=latency_ms,
            status="failed",
            error_code=error_code,
            error_detail=detail,
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            execution_id=execution_id,
            trust_tier=TrustTier.UNTRUSTED,
            result_trust=ResultTrust.UNVERIFIED,
            data_classification=DataClassification.PUBLIC,
        )

    def _get_registration(self, plugin_id: str):
        if self._registry is None:
            raise ExtensionNotFoundError(plugin_id)
        registration = self._registry.get(plugin_id)
        if registration is None:
            raise ExtensionNotFoundError(plugin_id)
        return registration

    def _get_health(self, plugin_id: str) -> str:
        if self._lifecycle is not None:
            record = self._lifecycle.get_health(plugin_id)
            if record is not None:
                if hasattr(record, "health"):
                    return record.health.value if hasattr(record.health, "value") else str(record.health)
                return record
        return "unknown"

    async def _check_permissions(self, manifest: ExtensionManifest, context: ExtensionExecutionContext, authorized_plan: Dict[str, Any], capability: Optional[ExtensionCapability]) -> List[str]:
        missing: List[str] = []
        granted = set(authorized_plan.get("allowed_capabilities", []))
        required_perms = self._get_required_permissions(manifest, capability)
        for perm in required_perms:
            if perm not in granted:
                missing.append(perm)
        return missing

    def _check_rbac(self, manifest: ExtensionManifest, context: ExtensionExecutionContext, capability: Optional[ExtensionCapability]) -> bool:
        """Check RBAC using trusted context roles."""
        required_roles = set(self._get_required_roles(manifest, capability))
        if not required_roles:
            return True
        granted_roles = set(context.roles)
        return bool(required_roles & granted_roles)

    def _check_tenant(self, manifest: ExtensionManifest, context: ExtensionExecutionContext) -> bool:
        """Check tenant isolation."""
        scope = manifest.tenant_scope
        if scope == TenantScope.SINGLE:
            return bool(context.tenant_id)
        if scope == TenantScope.MULTI:
            return context.tenant_id in set(manifest.allowed_tenant_ids)
        if scope == TenantScope.GLOBAL:
            return False
        return False

    def _check_budget(self, context: ExtensionExecutionContext) -> bool:
        """Check execution budget."""
        budget = context.budget
        if budget is None:
            return True
        if isinstance(budget, ExecutionBudget):
            return budget.max_duration_ms > 0
        return True

    async def _check_gate(
        self,
        principal: str,
        tenant: str,
        plugin_id: str,
        capability_id: str,
        side_effect_level: str,
        resource_scope: Mapping[str, Any],
        permissions: tuple[str, ...],
        risk_class: str,
        requires_network: bool,
        requires_filesystem: bool,
        requires_credentials: bool,
        requires_external_api: bool,
        trust_tier: str,
        isolation_mode: str,
    ) -> Tuple[bool, str, List[str], bool, Mapping[str, Any]]:
        """Authorize side effects through the gate port.

        If the gate port is absent, fail closed for governed side effects.
        """
        if self._gate_port is None:
            return False, "", ["policy_unavailable"], True, resource_scope

        try:
            return await self._gate_port.authorize(
                principal=principal,
                tenant=tenant,
                plugin_id=plugin_id,
                capability_id=capability_id,
                side_effect_level=side_effect_level,
                resource_scope=resource_scope,
                permissions=permissions,
                risk_class=risk_class,
                requires_network=requires_network,
                requires_filesystem=requires_filesystem,
                requires_credentials=requires_credentials,
                requires_external_api=requires_external_api,
                trust_tier=trust_tier,
                isolation_mode=isolation_mode,
            )
        except Exception as exc:
            logger.warning("Gate port failed for %s/%s: %s", plugin_id, capability_id, exc)
            return False, "", ["gate_error"], True, resource_scope

    def _check_isolation_policy(self, manifest: ExtensionManifest) -> bool:
        """Validate trust tier / isolation mode combination."""
        allowed = {
            TrustTier.BUILTIN_TRUSTED: {ExecutionIsolationMode.IN_PROCESS},
            TrustTier.FIRST_PARTY: {ExecutionIsolationMode.IN_PROCESS, ExecutionIsolationMode.SUBPROCESS},
            TrustTier.SIGNED_THIRD_PARTY: {ExecutionIsolationMode.SUBPROCESS, ExecutionIsolationMode.CONTAINER, ExecutionIsolationMode.WASM},
            TrustTier.UNTRUSTED: {ExecutionIsolationMode.CONTAINER, ExecutionIsolationMode.WASM},
            TrustTier.REMOTE: {ExecutionIsolationMode.REMOTE},
        }
        trust_tier = getattr(manifest, "trust_tier", TrustTier.UNTRUSTED)
        isolation_mode = getattr(manifest, "isolation_mode", ExecutionIsolationMode.IN_PROCESS)
        allowed_set = allowed.get(trust_tier, set())
        return isolation_mode in allowed_set

    def _check_network_policy(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability], request: ExtensionExecutionRequest) -> bool:
        """Check network policy for side-effecting capabilities."""
        if not (manifest.requires_network or (capability and getattr(capability, "requires_network", False))):
            return True
        if self._network_policy is None:
            return False
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self._network_policy.check_allowed(
                    manifest.id,
                    request.capability,
                    request.payload,
                    None,
                )
            )
        except Exception:
            return False

    def _check_credential_policy(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> bool:
        """Check credential policy."""
        if not (manifest.requires_credentials or (capability and getattr(capability, "requires_credentials", False))):
            return True
        return False

    def _check_filesystem_policy(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability], request: ExtensionExecutionRequest) -> bool:
        """Check filesystem policy."""
        if not (manifest.requires_filesystem or (capability and getattr(capability, "requires_filesystem", False))):
            return True
        return False

    def _check_prompt_contract(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability], authorized_plan: Optional[Dict[str, Any]] = None) -> bool:
        """Check prompt contract eligibility.

        If the manifest or capability declares prompt_contract_id/prompt_version,
        the authorized plan must carry a matching prompt contract reference.
        """
        if capability:
            declared_id = getattr(capability, "prompt_contract_id", None) or manifest.prompt_contract_id
            declared_version = getattr(capability, "prompt_version", None) or manifest.prompt_version
        else:
            declared_id = manifest.prompt_contract_id
            declared_version = manifest.prompt_version

        if not declared_id:
            return True

        plan_contracts = (authorized_plan or {}).get("prompt_contracts", {})
        if declared_id not in plan_contracts:
            return False

        if declared_version and plan_contracts.get(declared_id) != declared_version:
            return False

        return True

    def _resolve_handler(self, registration: Any) -> Optional[Any]:
        instance = registration.instance
        if instance is None:
            return None
        if hasattr(instance, "execute"):
            return instance.execute
        if hasattr(instance, "run"):
            return instance.run
        return None

    async def _invoke(self, handler: Any, request: ExtensionExecutionRequest) -> Any:
        if asyncio.iscoroutinefunction(handler):
            return await handler(request.payload, request.context)
        return handler(request.payload, request.context)

    def _infer_side_effects(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> List[str]:
        """Infer side effects from manifest and capability declarations."""
        effects: List[str] = []
        if manifest.requires_network or (capability and getattr(capability, "requires_network", False)):
            effects.append("network")
        if manifest.requires_filesystem or (capability and getattr(capability, "requires_filesystem", False)):
            effects.append("filesystem")
        if manifest.requires_credentials or (capability and getattr(capability, "requires_credentials", False)):
            effects.append("credentials")
        if manifest.requires_external_api:
            effects.append("external_api")

        side_effect_level = getattr(capability, "side_effect_level", None) if capability else manifest.side_effect_level
        if side_effect_level == SideEffectLevel.WRITE:
            effects.append("write")
        elif side_effect_level == SideEffectLevel.EXTERNAL:
            effects.extend(["write", "external"])

        return effects

    def _audit(self, **kwargs: Any) -> None:
        """Emit a structured audit event."""
        event = kwargs.get("event")
        if event is None:
            return
        if self._audit_sink:
            try:
                self._audit_sink(kwargs)
            except Exception as exc:
                logger.warning("Audit sink failed: %s", exc)
        logger.info(
            "extension_audit event=%s request_id=%s correlation_id=%s user_id=%s tenant_id=%s plugin_id=%s plugin_version=%s capability=%s execution_id=%s policy_decision_id=%s trust_tier=%s isolation_mode=%s side_effect_level=%s latency_ms=%s status=%s error_code=%s",
            event,
            kwargs.get("request_id"),
            kwargs.get("correlation_id"),
            kwargs.get("user_id"),
            kwargs.get("tenant_id"),
            kwargs.get("plugin_id"),
            kwargs.get("plugin_version"),
            kwargs.get("capability"),
            kwargs.get("execution_id"),
            kwargs.get("policy_decision_id"),
            kwargs.get("trust_tier"),
            kwargs.get("isolation_mode"),
            kwargs.get("side_effect_level"),
            kwargs.get("latency_ms"),
            kwargs.get("status"),
            kwargs.get("error_code"),
        )


class _DefaultSchemaValidator:
    def validate_input(self, manifest: ExtensionManifest, payload: Dict[str, Any], capability: Optional[ExtensionCapability] = None) -> List[str]:
        schema = None
        if capability and capability.input_schema:
            schema = capability.input_schema
        elif manifest.input_schema:
            schema = manifest.input_schema

        if not schema:
            return []
        return self._validate(payload, schema, "input")

    def validate_output(self, manifest: ExtensionManifest, payload: Any, capability: Optional[ExtensionCapability] = None) -> List[str]:
        schema = None
        if capability and capability.output_schema:
            schema = capability.output_schema
        elif manifest.output_schema:
            schema = manifest.output_schema

        if not schema:
            return []
        return self._validate(payload if isinstance(payload, dict) else {"value": payload}, schema, "output")

    def _validate(self, payload: Dict[str, Any], schema: Dict[str, Any], direction: str) -> List[str]:
        errors: List[str] = []
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        allow_additional = schema.get("additionalProperties", True)

        for field_name in required:
            if field_name not in payload:
                errors.append(f"Missing required {direction} field: {field_name}")

        for key in payload:
            if key not in properties:
                if not allow_additional:
                    errors.append(f"Unexpected {direction} field: {key}")
                continue
            field_schema = properties[key]
            value = payload[key]
            expected_type = field_schema.get("type")
            if expected_type:
                type_map: dict[str, type | tuple[type, ...]] = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
                expected = type_map.get(expected_type)
                if expected and not isinstance(value, expected):
                    errors.append(f"Field '{key}' must be {expected_type}, got {type(value).__name__}")

        return errors


__all__ = ["ExtensionExecutionService"]

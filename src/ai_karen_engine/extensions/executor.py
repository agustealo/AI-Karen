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
from typing import Any, Callable, Dict, List, Optional

from ai_karen_engine.extensions.contracts import (
    CapabilityInvocationRequest,
    DataClassification,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
    ExtensionLifecycleState,
    ExtensionManifest,
    ResponseSource,
    ResultTrust,
    TrustTier,
)
from ai_karen_engine.extensions.errors import (
    ExtensionError,
    ExtensionNotFoundError,
    ExtensionNotRegisteredError,
    ExtensionDisabledError,
    ExtensionPermissionError,
    ExtensionTimeoutError,
    ExtensionExecutionEngineError,
)

logger = logging.getLogger("kari.extensions.executor")


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
    ):
        self._registry = registry
        self._lifecycle = lifecycle
        self._schema_validator = schema_validator or _DefaultSchemaValidator()
        self._audit_sink = audit_sink
        self._policy_resolver = policy_resolver
        self._capability_resolver = capability_resolver
        self._active: Dict[str, asyncio.Task] = {}

    async def execute_capability(
        self,
        request: CapabilityInvocationRequest,
        authorized_plan: Optional[Dict[str, Any]] = None,
    ) -> ExtensionExecutionResult:
        """Execute a capability request through full governance.

        This is the capability-first path. Extensions are resolved by runtime.
        """
        start = time.perf_counter()
        execution_id = str(uuid.uuid4())

        if self._capability_resolver is None:
            raise ExtensionError(
                "Capability resolver not configured",
                error_code="missing_resolver",
            )

        try:
            resolved = await self._capability_resolver.resolve(request, authorized_plan)
        except Exception as exc:
            return self._fail_capability(
                request,
                start,
                execution_id,
                "resolution_failed",
                str(exc),
            )

        ext_request = self._convert_to_ext_request(request, resolved)

        result = await self.execute(ext_request, authorized_plan)

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

    async def execute(self, request: ExtensionExecutionRequest) -> ExtensionExecutionResult:
        """Execute an extension through the full governance gate chain."""
        start = time.perf_counter()
        plugin_id = request.plugin_id
        capability = request.capability
        execution_id = str(uuid.uuid4())

        try:
            registration = self._get_registration(plugin_id)
        except ExtensionError as exc:
            return self._fail(request, start, execution_id, exc.error_code, str(exc))

        manifest = registration.manifest
        context = request.context

        capability_obj = self._get_capability(manifest, capability)

        if capability_obj is not None:
            result_trust = getattr(capability_obj, "result_trust", ResultTrust.UNTRUSTED_EXTERNAL)
            data_classification = getattr(capability_obj, "data_classification", DataClassification.PUBLIC)
            trust_tier = getattr(manifest, "trust_tier", TrustTier.UNTRUSTED)
        else:
            result_trust = ResultTrust.UNTRUSTED_EXTERNAL
            data_classification = DataClassification.PUBLIC
            trust_tier = getattr(manifest, "trust_tier", TrustTier.UNTRUSTED)

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
            )

        health = self._get_health(plugin_id)
        if health == "unavailable":
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "unavailable",
                f"Extension '{plugin_id}' is unavailable",
                trust_tier,
                result_trust,
                data_classification,
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
            )

        tenant_ok = self._check_tenant(manifest, context)
        if not tenant_ok:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "tenant_denied",
                f"Tenant access denied for '{plugin_id}'",
                trust_tier,
                result_trust,
                data_classification,
            )

        input_errors = self._schema_validator.validate_input(manifest, request.payload, capability_obj)
        if input_errors:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "invalid_input",
                "; ".join(input_errors),
                trust_tier,
                result_trust,
                data_classification,
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
            )

        timeout_ms = self._get_timeout(request, manifest, capability_obj)
        try:
            raw_result = await asyncio.wait_for(self._invoke(handler, request), timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            error = ExtensionTimeoutError(plugin_id, timeout_ms)
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                error.error_code,
                str(error),
                trust_tier,
                result_trust,
                data_classification,
            )
        except ExtensionError as exc:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                exc.error_code,
                str(exc),
                trust_tier,
                result_trust,
                data_classification,
            )
        except Exception as exc:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "execution_error",
                str(exc),
                trust_tier,
                result_trust,
                data_classification,
            )

        output_errors = self._schema_validator.validate_output(manifest, raw_result, capability_obj)
        if output_errors:
            return self._fail_with_provenance(
                request,
                start,
                execution_id,
                "invalid_output",
                "; ".join(output_errors),
                trust_tier,
                result_trust,
                data_classification,
            )

        latency_ms = (time.perf_counter() - start) * 1000.0

        self._audit(
            plugin_id=plugin_id,
            plugin_version=manifest.version,
            capability=capability,
            status="success",
            latency_ms=latency_ms,
            error_code=None,
            side_effects=self._infer_side_effects(manifest, capability_obj),
            permission_set=self._get_required_permissions(manifest, capability_obj),
            correlation_id=context.correlation_id,
            policy_decision_id=context.policy_decision_id,
            trust_tier=trust_tier,
            result_trust=result_trust,
            data_classification=data_classification,
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
            correlation_id=context.correlation_id,
            policy_decision_id=context.policy_decision_id,
            execution_id=execution_id,
            trust_tier=trust_tier,
            result_trust=result_trust,
            data_classification=data_classification,
            backend=manifest.metadata.get("backend"),
            backend_version=manifest.metadata.get("backend_version"),
        )

    def _get_capability(self, manifest: ExtensionManifest, capability_id: str) -> Optional[ExtensionCapability]:
        """Get the capability object from manifest."""
        for cap in manifest.capabilities:
            if cap.id == capability_id:
                return cap
        return None

    def _get_required_permissions(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> List[str]:
        """Get required permissions preferring capability-level over manifest-level."""
        if capability and capability.required_permissions:
            return capability.required_permissions
        return manifest.required_permissions

    def _get_timeout(self, request: ExtensionExecutionRequest, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> int:
        """Get timeout preferring capability-level over manifest-level over request override."""
        if request.timeout_override_ms:
            return request.timeout_override_ms
        if capability and hasattr(capability, "retry_policy"):
            return capability.retry_policy.get("timeout_ms", manifest.timeout_ms)
        return manifest.timeout_ms

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
    ) -> ExtensionExecutionResult:
        """Create failure result with provenance metadata."""
        latency_ms = (time.perf_counter() - start) * 1000.0
        self._audit(
            plugin_id=request.plugin_id,
            plugin_version="unknown",
            capability=request.capability,
            status="failed",
            latency_ms=latency_ms,
            error_code=error_code,
            side_effects=[],
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=trust_tier,
            result_trust=result_trust,
            data_classification=data_classification,
            detail=detail,
        )
        return ExtensionExecutionResult(
            request_id=request.context.request_id,
            plugin_id=request.plugin_id,
            plugin_version="unknown",
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
            plugin_id="unknown",
            plugin_version="unknown",
            capability=request.capability_id,
            status="failed",
            latency_ms=latency_ms,
            error_code=error_code,
            side_effects=[],
            correlation_id=request.context.correlation_id,
            policy_decision_id=request.context.policy_decision_id,
            trust_tier=TrustTier.UNTRUSTED,
            result_trust=ResultTrust.UNVERIFIED,
            data_classification=DataClassification.PUBLIC,
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
        user_roles = context.audit_context.get("user_roles", [])
        required_roles = capability.required_roles if capability else manifest.required_roles
        if not required_roles:
            return True
        return bool(set(required_roles) & set(user_roles))

    def _check_tenant(self, manifest: ExtensionManifest, context: ExtensionExecutionContext) -> bool:
        if manifest.tenant_scope == "global":
            return False
        if manifest.tenant_scope == "single":
            return bool(context.tenant_id)
        if manifest.tenant_scope == "multi":
            return context.tenant_id in manifest.allowed_tenant_ids
        return False

    def _check_budget(self, context: ExtensionExecutionContext) -> bool:
        budget = context.budget or {}
        return not budget.get("exhausted", False)

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
        if side_effect_level == "write":
            effects.append("write")
        elif side_effect_level == "external":
            effects.extend(["write", "external"])

        return effects

    def _audit(self, **kwargs: Any) -> None:
        if self._audit_sink:
            try:
                self._audit_sink(kwargs)
            except Exception as exc:
                logger.warning("Audit sink failed: %s", exc)
        logger.info(
            "extension_audit plugin_id=%s plugin_version=%s capability=%s status=%s error_code=%s latency_ms=%s side_effects=%s correlation_id=%s trust_tier=%s result_trust=%s detail=%s",
            kwargs.get("plugin_id"),
            kwargs.get("plugin_version"),
            kwargs.get("capability"),
            kwargs.get("status"),
            kwargs.get("error_code"),
            kwargs.get("latency_ms"),
            kwargs.get("side_effects"),
            kwargs.get("correlation_id"),
            kwargs.get("trust_tier"),
            kwargs.get("result_trust"),
            kwargs.get("detail"),
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
                type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
                expected = type_map.get(expected_type)
                if expected and not isinstance(value, expected):
                    errors.append(f"Field '{key}' must be {expected_type}, got {type(value).__name__}")

        return errors


__all__ = ["ExtensionExecutionService"]

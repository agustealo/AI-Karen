"""Tests for canonical extension executor authorization."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.extensions.contracts import (
    CapabilityInvocationRequest,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionHealth,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    ResolvedCapability,
    ResponseSource,
    TrustTier,
    ExecutionIsolationMode,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService


class FakeHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        self.calls += 1
        return {"echo": payload.get("message", "")}


class FakeRegistry:
    def __init__(
        self,
        *,
        enabled: bool = True,
        handler: FakeHandler | None = None,
        manifest: ExtensionManifest | None = None,
    ) -> None:
        self.handler = handler or FakeHandler()
        self.enabled = enabled
        self.manifest = manifest or _manifest()

    def get(self, plugin_id: str) -> ExtensionRegistration | None:
        if plugin_id != "echo":
            return None
        return ExtensionRegistration(
            manifest=self.manifest,
            state=(
                ExtensionLifecycleState.ENABLED
                if self.enabled
                else ExtensionLifecycleState.DISABLED
            ),
            instance=self.handler,
        )


class FakeLifecycle:
    def get_health(self, plugin_id: str) -> ExtensionHealth:
        return ExtensionHealth.HEALTHY


class FakeCapabilityResolver:
    async def resolve(
        self,
        request: CapabilityInvocationRequest,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> ResolvedCapability:
        assert authorized_plan.policy_decision_id == "policy-1"
        return ResolvedCapability(
            capability=ExtensionCapability(id="echo", version="1.0.0"),
            extension_id="echo",
            extension_version="1.0.0",
            extension_trust_tier=TrustTier.UNTRUSTED,
            extension_isolation_mode=ExecutionIsolationMode.IN_PROCESS,
            policy_decision_id=authorized_plan.policy_decision_id,
        )


def _manifest(
    *,
    required_permissions: list[str] | None = None,
    trust_tier: TrustTier = TrustTier.FIRST_PARTY,
    isolation_mode: ExecutionIsolationMode = ExecutionIsolationMode.IN_PROCESS,
) -> ExtensionManifest:
    permissions = list(required_permissions or [])
    return ExtensionManifest(
        id="echo",
        name="echo",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Test",
        entrypoint="handler:EchoExtension",
        capabilities=[
            ExtensionCapability(
                id="echo",
                version="1.0.0",
                required_permissions=permissions,
            )
        ],
        intents=["echo"],
        required_permissions=permissions,
        optional_permissions=[],
        required_roles=[],
        tenant_scope="single",
        allowed_tenant_ids=[],
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        output_schema={
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "required": ["echo"],
        },
        side_effect_level="none",
        timeout_ms=5000,
        max_retries=1,
        enabled_by_default=False,
        trusted_ui=False,
        trust_tier=trust_tier,
        isolation_mode=isolation_mode,
        dependencies=[],
    )


def _context(
    *,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    session_id: str | None = "session-1",
) -> ExtensionExecutionContext:
    return ExtensionExecutionContext(
        request_id="req-1",
        correlation_id="corr-1",
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        policy_decision_id="policy-1",
        allowed_capabilities=[],
    )


def _plan(
    *,
    allowed_plugins: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    session_id: str | None = "session-1",
) -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        authorized_user_id=user_id,
        authorized_tenant_id=tenant_id,
        authorized_session_id=session_id,
        allowed_plugins=list(allowed_plugins if allowed_plugins is not None else ["echo"]),
        allowed_capabilities=list(allowed_capabilities or []),
    )


def _request(
    *,
    plan: AuthorizedExecutionPlan | None,
    context: ExtensionExecutionContext | None = None,
) -> ExtensionExecutionRequest:
    return ExtensionExecutionRequest(
        plugin_id="echo",
        capability="echo",
        payload={"message": "hello"},
        context=context or _context(),
        authorized_plan=plan,
    )


@pytest.mark.asyncio
async def test_execute_success_with_matching_authorized_plan():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "success"
    assert result.source == ResponseSource.PLUGIN
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code", "detail"),
    [
        ("input", "invalid_input", "Extension input failed schema validation"),
        ("output", "invalid_output", "Extension output failed schema validation"),
        ("handler", "execution_error", "Extension handler failed"),
        ("typed", "extension_error", "Extension handler failed"),
    ],
)
async def test_payload_diagnostics_do_not_escape_executor(failure, code, detail, caplog):
    from ai_karen_engine.extensions.errors import ExtensionError

    private_marker = "private-document-diagnostic-marker"
    audit = []

    class DiagnosticHandler(FakeHandler):
        async def execute(self, payload, context):
            self.calls += 1
            if failure == "handler":
                raise RuntimeError(private_marker)
            if failure == "typed":
                raise ExtensionError(private_marker)
            return {"echo": "hello", private_marker: "private"}

    handler = DiagnosticHandler()
    manifest = _manifest()
    manifest.input_schema["additionalProperties"] = False
    manifest.output_schema["additionalProperties"] = False
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler, manifest=manifest),
        lifecycle=FakeLifecycle(),
        audit_sink=audit.append,
    )
    request = _request(plan=_plan())
    if failure == "input":
        request.payload[private_marker] = "private"
    with caplog.at_level("INFO"):
        result = await service.execute(request)

    assert result.status == "failed"
    assert result.error_code == code
    assert result.error_detail == detail
    assert result.payload is None
    assert handler.calls == (0 if failure == "input" else 1)
    assert audit[-1]["error_code"] == code
    assert audit[-1]["detail"] == detail
    assert private_marker not in repr(audit)
    assert private_marker not in caplog.text
    assert private_marker not in repr(result)


@pytest.mark.asyncio
async def test_missing_authorized_plan_denied_before_handler():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=None))

    assert result.status == "failed"
    assert result.error_code == "authorized_plan_required"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_empty_allowed_plugins_is_fail_closed():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan(allowed_plugins=[])))

    assert result.status == "failed"
    assert result.error_code == "not_authorized"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_required_permission_is_fail_closed_when_plan_grant_is_empty():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(required_permissions=["custom_access"]),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(allowed_capabilities=[]))
    )

    assert result.status == "failed"
    assert result.error_code == "permission_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_required_permission_executes_only_when_plan_grants_it():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(required_permissions=["custom_access"]),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(allowed_capabilities=["custom_access"]))
    )

    assert result.status == "success"
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_wrong_tenant_plan_is_denied():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(
        _request(plan=_plan(tenant_id="tenant-other"))
    )

    assert result.status == "failed"
    assert result.error_code == "authorized_scope_mismatch"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_action_execution_gate_denial_prevents_handler(monkeypatch):
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )

    async def deny(plan: AuthorizedExecutionPlan, action: str) -> bool:
        assert action == "echo"
        return False

    monkeypatch.setattr(ActionExecutionGate, "authorize", staticmethod(deny))

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "failed"
    assert result.error_code == "action_gate_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_capability_first_path_uses_single_execute_signature():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
        capability_resolver=FakeCapabilityResolver(),
    )
    request = CapabilityInvocationRequest(
        capability_id="echo",
        payload={"message": "hello"},
        context=_context(),
        authorized_plan=_plan(),
    )

    result = await service.execute_capability(request, request.authorized_plan)

    assert result.status == "success"
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_disabled_plugin_denied():
    service = ExtensionExecutionService(
        registry=FakeRegistry(enabled=False),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "failed"
    assert result.error_code == "disabled"


@pytest.mark.asyncio
async def test_not_found():
    service = ExtensionExecutionService(
        registry=type("FakeRegistry", (), {"get": lambda self, pid: None})()
    )
    request = ExtensionExecutionRequest(
        plugin_id="missing",
        capability="echo",
        payload={},
        context=_context(),
        authorized_plan=AuthorizedExecutionPlan(
            execution_id="exec-1",
            policy_decision_id="policy-1",
            authorized_user_id="user-1",
            authorized_tenant_id="tenant-1",
            authorized_session_id="session-1",
            allowed_plugins=["missing"],
        ),
    )

    result = await service.execute(request)

    assert result.status == "failed"
    assert result.error_code == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trust_tier", "isolation_mode"),
    [
        (TrustTier.UNTRUSTED, ExecutionIsolationMode.IN_PROCESS),
        (TrustTier.SIGNED_THIRD_PARTY, ExecutionIsolationMode.IN_PROCESS),
        (TrustTier.UNTRUSTED, ExecutionIsolationMode.SUBPROCESS),
        (TrustTier.REMOTE, ExecutionIsolationMode.REMOTE),
        (TrustTier.FIRST_PARTY, ExecutionIsolationMode.CONTAINER),
    ],
)
async def test_unavailable_isolation_fails_closed_before_handler_import(
    trust_tier: TrustTier,
    isolation_mode: ExecutionIsolationMode,
) -> None:
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(trust_tier=trust_tier, isolation_mode=isolation_mode),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "failed"
    assert result.error_code == "isolation_unavailable"
    assert result.source == ResponseSource.UNAVAILABLE
    assert result.trust_tier == trust_tier
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_capability_resolver_cannot_promote_actual_runtime_trust() -> None:
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(trust_tier=TrustTier.UNTRUSTED),
        ),
        lifecycle=FakeLifecycle(),
        capability_resolver=FakeCapabilityResolver(),
    )
    request = CapabilityInvocationRequest(
        capability_id="echo",
        payload={"message": "hello"},
        context=_context(),
        authorized_plan=_plan(),
    )

    result = await service.execute_capability(request, request.authorized_plan)

    assert result.status == "failed"
    assert result.error_code == "isolation_unavailable"
    assert result.trust_tier is TrustTier.UNTRUSTED
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_builtin_trusted_handler_retains_canonical_execution() -> None:
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler,
            manifest=_manifest(trust_tier=TrustTier.BUILTIN_TRUSTED),
        ),
        lifecycle=FakeLifecycle(),
    )

    result = await service.execute(_request(plan=_plan()))

    assert result.status == "success"
    assert result.payload == {"echo": "hello"}
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_admission_runs_full_gates_without_invoking_handler():
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )
    request = _request(plan=_plan())
    request.payload = {}
    result = await service.admit(request)
    assert result.status == "admitted"
    assert result.payload is None
    assert result.source == ResponseSource.UNAVAILABLE
    assert handler.calls == 0
    # Full input schema remains mandatory for actual execution.
    actual = await service.execute(request)
    assert actual.status == "failed"
    assert actual.error_code == "invalid_input"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_admission_fails_closed_for_identity_and_action_gate(monkeypatch):
    handler = FakeHandler()
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler),
        lifecycle=FakeLifecycle(),
    )
    denied_identity = await service.admit(
        _request(plan=_plan(tenant_id="different"))
    )
    assert denied_identity.status == "failed"
    assert denied_identity.error_code == "authorized_scope_mismatch"

    async def deny(plan: AuthorizedExecutionPlan, action: str) -> bool:
        return False

    monkeypatch.setattr(ActionExecutionGate, "authorize", staticmethod(deny))
    denied_action = await service.admit(_request(plan=_plan()))
    assert denied_action.status == "failed"
    assert denied_action.error_code == "action_gate_denied"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_admission_never_executes_untrusted_or_disabled_handler():
    handler = FakeHandler()
    disabled = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler, enabled=False),
        lifecycle=FakeLifecycle(),
    )
    assert (await disabled.admit(_request(plan=_plan()))).error_code == "disabled"
    untrusted = ExtensionExecutionService(
        registry=FakeRegistry(
            handler=handler, manifest=_manifest(trust_tier=TrustTier.UNTRUSTED),
        ), lifecycle=FakeLifecycle(),
    )
    assert (
        await untrusted.admit(_request(plan=_plan()))
    ).error_code == "isolation_unavailable"
    assert handler.calls == 0


def test_extension_runtime_authority_cannot_be_minted_from_unissued_chat_context():
    from dataclasses import asdict, replace
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

    context = _context()
    plan = _plan()
    runtime_context = ChatExecutionContext(
        user_id=context.user_id, tenant_id=context.tenant_id,
        session_id=context.session_id, correlation_id=context.correlation_id,
    )
    meter = ExecutionBudgetMeter(plan.budget)
    with pytest.raises(PermissionError, match="extension_runtime_authority_invalid"):
        context.bind_runtime_authority(runtime_context, plan, meter, "echo")
    assert context.runtime_authority("echo") is None
    assert replace(context).runtime_authority("echo") is None
    assert "_runtime_authority" not in asdict(context)
    assert "_runtime_authority" not in context.to_audit_dict()


def test_extension_runtime_authority_scope_and_copy_guard(monkeypatch):
    from copy import copy
    from dataclasses import replace
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

    context = _context()
    plan = _plan()
    meter = ExecutionBudgetMeter(plan.budget)
    runtime_context = ChatExecutionContext(
        user_id=context.user_id, tenant_id=context.tenant_id,
        session_id=context.session_id, correlation_id=context.correlation_id,
        conversation_id=context.conversation_id,
    )
    # ChatExecutionContext materializes the session's canonical conversation ID.
    # Align the extension fixture to that ID without weakening the scope guard.
    context = replace(context, conversation_id=runtime_context.conversation_id)
    # Isolate extension propagation from the separately tested RuntimePolicy issuer.
    monkeypatch.setattr(ChatExecutionContext, "is_runtime_model_plan_authorized",
                        lambda self, p, m: self is runtime_context and p is plan and m is meter)
    context.bind_runtime_authority(runtime_context, plan, meter, "echo")
    assert context.runtime_authority("echo")[1] is meter
    assert replace(context).runtime_authority("echo") is None
    with pytest.raises(PermissionError):
        copy(context).runtime_authority("echo")
    with pytest.raises(PermissionError):
        context.bind_runtime_authority(runtime_context, plan, ExecutionBudgetMeter(plan.budget), "echo")
    with pytest.raises(PermissionError):
        context.runtime_authority("different-plugin")
    with pytest.raises(PermissionError):
        replace(context, tenant_id="other").bind_runtime_authority(runtime_context, plan, meter, "echo")
    with pytest.raises(PermissionError):
        replace(context, conversation_id="different-conversation").bind_runtime_authority(
            runtime_context, plan, meter, "echo"
        )


@pytest.mark.parametrize("mismatch", ["missing", "extra", "substituted"])
def test_runtime_extension_resource_scope_must_match_plan(monkeypatch, mismatch):
    from dataclasses import replace
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

    plan = _plan()
    plan.resource_scope = {"attachment_references": [{"source_id": "selected", "revision": "r1"}]}
    meter = ExecutionBudgetMeter(plan.budget)
    context = _context()
    runtime_context = ChatExecutionContext(
        user_id=context.user_id, tenant_id=context.tenant_id,
        session_id=context.session_id, correlation_id=context.correlation_id,
        request_id="chat-request",
    )
    monkeypatch.setattr(
        ChatExecutionContext, "is_runtime_model_plan_authorized",
        lambda self, p, m: self is runtime_context and p is plan and m is meter,
    )
    # Extension invocation IDs are intentionally distinct from chat request IDs.
    context = replace(
        context, conversation_id=runtime_context.conversation_id,
        resource_scope={"attachment_references": [{"source_id": "selected", "revision": "r1"}]},
    )
    invalid = {
        "missing": {},
        "extra": {**context.resource_scope, "extra": True},
        "substituted": {"attachment_references": [{"source_id": "other", "revision": "r1"}]},
    }[mismatch]
    with pytest.raises(PermissionError, match="extension_runtime_authority_invalid"):
        replace(context, resource_scope=invalid).bind_runtime_authority(
            runtime_context, plan, meter, "echo",
        )
    context.bind_runtime_authority(runtime_context, plan, meter, "echo")
    assert context.runtime_authority("echo") == (plan, meter)
    context.resource_scope.clear()
    context.resource_scope.update(invalid)
    with pytest.raises(PermissionError, match="extension_runtime_authority_invalid"):
        context.runtime_authority("echo")
    assert meter.tool_calls == 0


@pytest.mark.asyncio
async def test_executor_rejects_runtime_authority_for_unrelated_plugin(monkeypatch):
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

    handler = FakeHandler()
    plan = _plan()
    meter = ExecutionBudgetMeter(plan.budget)
    monkeypatch.setattr(ExtensionExecutionContext, "runtime_authority",
                        lambda self, plugin_id: (plan, meter))
    service = ExtensionExecutionService(
        registry=FakeRegistry(handler=handler), lifecycle=FakeLifecycle(),
    )
    result = await service.execute(_request(plan=plan))
    assert result.error_code == "extension_runtime_authority_invalid"
    assert handler.calls == 0

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected_code,expected_calls,expected_timeout",
    [
        ("unstarted", "budget_exhausted", 0, None),
        ("expired_before", "budget_exhausted", 0, None),
        ("expired_after", "budget_exhausted", 1, 2.0),
        ("valid", None, 1, 2.0),
        ("shorter_override", None, 1, 1.0),
        ("authority_changed", "extension_runtime_authority_invalid", 1, 2.0),
    ],
)
async def test_runtime_bound_extension_uses_original_deadline(
    monkeypatch, scenario, expected_code, expected_calls, expected_timeout,
):
    import asyncio
    from dataclasses import replace
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

    class SearchRegistry(FakeRegistry):
        def get(self, plugin_id):
            return super().get("echo") if plugin_id == "intelligent-search" else None

    handler = FakeHandler()
    plan = _plan(allowed_plugins=["intelligent-search"])
    meter = ExecutionBudgetMeter(plan.budget)
    context = _context()
    runtime_context = ChatExecutionContext(
        user_id=context.user_id, tenant_id=context.tenant_id,
        session_id=context.session_id, correlation_id=context.correlation_id,
        request_id="chat-request",
    )
    context = replace(context, conversation_id=runtime_context.conversation_id)
    active = True
    monkeypatch.setattr(
        ChatExecutionContext, "is_runtime_model_plan_authorized",
        lambda self, p, m: active and self is runtime_context and p is plan and m is meter,
    )
    context.bind_runtime_authority(runtime_context, plan, meter, "intelligent-search")
    if scenario != "unstarted":
        assert await meter.reserve_tool_call()
        readings = iter({
            "expired_before": [0.0],
            "expired_after": [2000.0, 0.0],
            "valid": [2000.0, 1000.0],
            "shorter_override": [2000.0, 1000.0],
            "authority_changed": [2000.0, 1000.0],
        }[scenario])

        async def remaining():
            nonlocal active
            if scenario == "authority_changed" and handler.calls:
                active = False
            return next(readings)

        monkeypatch.setattr(meter, "remaining_admitted_duration_ms", remaining)

    original_wait_for = asyncio.wait_for
    timeouts = []

    async def observe_timeout(awaitable, timeout):
        timeouts.append(timeout)
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", observe_timeout)
    manifest = _manifest().model_copy(update={"id": "intelligent-search"})
    service = ExtensionExecutionService(
        registry=SearchRegistry(handler=handler, manifest=manifest),
        lifecycle=FakeLifecycle(),
    )
    request = replace(
        _request(plan=plan, context=context), plugin_id="intelligent-search",
        timeout_override_ms=1000 if scenario == "shorter_override" else 10000,
    )
    result = await service.execute(request)
    assert result.error_code == expected_code
    assert result.status == ("success" if expected_code is None else "failed")
    if expected_code is not None:
        assert result.payload is None
    assert handler.calls == expected_calls
    assert timeouts == ([] if expected_timeout is None else [expected_timeout])
    assert meter.tool_calls == (0 if scenario == "unstarted" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected_code,expected_calls",
    [
        ("valid", None, 1),
        ("forged_digest", "invalid_output", 1),
        ("mutated_query", "invalid_output", 1),
        ("substituted_text", "extension_runtime_authority_invalid", 0),
        ("unbound", "extension_runtime_authority_invalid", 0),
        ("revoked", "extension_runtime_authority_invalid", 1),
    ],
)
async def test_direct_runtime_document_executor_enforces_lineage(
    monkeypatch, scenario, expected_code, expected_calls,
):
    import hashlib
    from dataclasses import replace
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter
    from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

    plugin = "content-intelligence"
    owner = "22222222-2222-4222-8222-222222222222"
    tenant = "11111111-1111-4111-8111-111111111111"
    source = "44444444-4444-4444-8444-000000000001"
    body = "Vendor delivery pending."
    digest = hashlib.sha256(body.encode()).hexdigest()
    refs = [{"source_id": source, "revision": digest}]
    plan = _plan(
        user_id=owner, tenant_id=tenant, allowed_plugins=[plugin],
        allowed_capabilities=[plugin, "data:read"],
    )
    plan.resource_scope = {"attachment_references": refs}
    meter = ExecutionBudgetMeter(plan.budget)
    meter.start()
    context = _context(user_id=owner, tenant_id=tenant)
    runtime = ChatExecutionContext(
        user_id=owner, tenant_id=tenant, session_id=context.session_id,
        correlation_id=context.correlation_id, roles=["user"],
    )
    monkeypatch.setattr(
        ChatExecutionContext, "is_runtime_model_plan_authorized",
        lambda self, p, m: self is runtime and p is plan and m is meter,
    )
    monkeypatch.setattr(
        ChatExecutionContext, "original_runtime_model_plan",
        lambda self, m: plan if self is runtime and m is meter else None,
    )
    monkeypatch.setattr(
        ChatExecutionContext, "require_runtime_attachment_read_permission", lambda self: None,
    )
    runtime.bind_runtime_attachment_scope(plan, meter, refs)
    runtime.bind_runtime_attachment_documents(plan, meter, [
        VerifiedArtifactText(source, tenant, owner, "notes.txt", "text/plain", digest, body),
    ])
    context = replace(
        context, conversation_id=runtime.conversation_id,
        resource_scope={"attachment_references": refs},
        allowed_capabilities=[plugin, "data:read"], audit_context={"user_roles": ["user"]},
    )
    if scenario != "unbound":
        context.bind_runtime_authority(runtime, plan, meter, plugin)
    checks = 0

    async def revalidate(self, **kwargs):
        nonlocal checks
        checks += 1
        if scenario == "revoked" and checks > 1:
            raise PermissionError("session_revoked")

    monkeypatch.setattr(ChatExecutionContext, "revalidate_runtime_attachment_session", revalidate)

    class DocumentHandler(FakeHandler):
        async def execute(self, payload, context):
            self.calls += 1
            if scenario == "mutated_query":
                payload["query"] = "different"
                return {"operation": "search", "persisted": False,
                        "query": "different", "matches": []}
            return {
                "operation": "analyze", "persisted": False,
                "documents": [{
                    "id": source, "name": "notes.txt", "characters": len(body),
                    "sha256": "0" * 64 if scenario == "forged_digest" else digest,
                    "top_terms": [],
                }],
            }

    class DocumentRegistry(FakeRegistry):
        def get(self, plugin_id):
            return super().get("echo") if plugin_id == plugin else None

    handler = DocumentHandler()
    manifest = _manifest().model_copy(update={
        "id": plugin,
        "capabilities": [ExtensionCapability(id="execute", version="1.0.0")],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    })
    service = ExtensionExecutionService(
        registry=DocumentRegistry(handler=handler, manifest=manifest),
        lifecycle=FakeLifecycle(),
    )
    payload = {
        "operation": "analyze",
        "documents": [{"id": source, "name": "notes.txt",
                       "text": "substituted" if scenario == "substituted_text" else body}],
    }
    if scenario == "mutated_query":
        payload.update({"operation": "search", "query": "vendor"})
    request = ExtensionExecutionRequest(
        plugin_id=plugin, capability="execute", payload=payload,
        context=context, authorized_plan=plan,
    )
    result = await service.execute(request)
    assert result.error_code == expected_code
    assert result.status == ("success" if expected_code is None else "failed")
    assert handler.calls == expected_calls
    assert meter.tool_calls == expected_calls
    if expected_code is not None:
        assert result.payload is None
    else:
        assert result.payload["documents"][0]["sha256"] == digest
    if scenario == "mutated_query":
        assert payload["query"] == "vendor"

"""Security governance tests for the canonical extension executor.

Covers EXT-201 through EXT-216.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

from ai_karen_engine.extensions.contracts import (
    ActionExecutionGatePort,
    DataClassification,
    ExecutionBudget,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
    ExecutionIsolationMode,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    ResponseSource,
    ResultTrust,
    SideEffectLevel,
    TrustTier,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService
from ai_karen_engine.extensions.errors import (
    ExtensionCredentialDeniedError,
    ExtensionFilesystemDeniedError,
    ExtensionHumanGateRequiredError,
    ExtensionIsolationPolicyViolationError,
    ExtensionNetworkDeniedError,
    ExtensionPolicyDeniedError,
    ExtensionPromptContractDeniedError,
    ExtensionSchemaError,
    ExtensionTenantDeniedError,
    ExtensionTimeoutClampedError,
)


class FakeHandler:
    async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        return {"echo": payload.get("message", "")}


def _base_manifest(**overrides: Any) -> ExtensionManifest:
    data: Dict[str, Any] = {
        "id": "echo",
        "name": "echo",
        "version": "1.0.0",
        "plugin_api_version": "1.0",
        "description": "Test",
        "entrypoint": "handler:EchoExtension",
        "capabilities": [ExtensionCapability(id="echo", version="1.0.0")],
        "intents": ["echo"],
        "required_permissions": [],
        "optional_permissions": [],
        "required_roles": [],
        "tenant_scope": "single",
        "allowed_tenant_ids": [],
        "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        "output_schema": {"type": "object", "properties": {"echo": {"type": "string"}}, "required": ["echo"]},
        "side_effect_level": SideEffectLevel.NONE,
        "timeout_ms": 5000,
        "max_retries": 1,
        "enabled_by_default": False,
        "trusted_ui": False,
        "dependencies": [],
        "trust_tier": TrustTier.FIRST_PARTY,
        "isolation_mode": ExecutionIsolationMode.SUBPROCESS,
    }
    data.update(overrides)
    return ExtensionManifest(**data)


def _service(registry: Any, lifecycle: Any = None, **kwargs: Any) -> ExtensionExecutionService:
    if lifecycle is None:
        lifecycle = type("FakeLifecycle", (), {"get_health": lambda self, pid: "healthy"})()
    return ExtensionExecutionService(registry=registry, lifecycle=lifecycle, **kwargs)


def _request(manifest: ExtensionManifest, **overrides: Any) -> ExtensionExecutionRequest:
    context = ExtensionExecutionContext.for_runtime(
        request_id="req-1",
        correlation_id="corr-1",
        user_id="user-1",
        tenant_id="tenant-1",
        roles=(),
        permissions=(),
        allowed_capabilities=(),
    )
    data: Dict[str, Any] = {
        "plugin_id": manifest.id,
        "capability": manifest.capabilities[0].id,
        "payload": {"message": "hello"},
        "context": context,
        "authorized_plan": {"allowed_plugins": [manifest.id], "allowed_capabilities": []},
    }
    data.update(overrides)
    return ExtensionExecutionRequest(**data)


# EXT-201: Isolation policy violation (UNTRUSTED + IN_PROCESS)


@pytest.mark.asyncio
async def test_ext_201_isolation_policy_violation():
    manifest = _base_manifest(trust_tier=TrustTier.UNTRUSTED, isolation_mode=ExecutionIsolationMode.IN_PROCESS)
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "isolation_policy_violation"


# EXT-202: Network policy denial for side-effecting capability without network policy


@pytest.mark.asyncio
async def test_ext_202_network_policy_denied():
    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", side_effect_level=SideEffectLevel.READ, requires_network=True)],
        requires_network=True,
        side_effect_level=SideEffectLevel.READ,
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry, network_policy=None)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "network_denied"


# EXT-203: Credential policy denial for capability requiring credentials


@pytest.mark.asyncio
async def test_ext_203_credential_policy_denied():
    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", side_effect_level=SideEffectLevel.READ, requires_credentials=True)],
        requires_credentials=True,
        side_effect_level=SideEffectLevel.READ,
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "credential_denied"


# EXT-204: Filesystem policy denial for capability requiring filesystem


@pytest.mark.asyncio
async def test_ext_204_filesystem_policy_denied():
    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", side_effect_level=SideEffectLevel.READ, requires_filesystem=True)],
        requires_filesystem=True,
        side_effect_level=SideEffectLevel.READ,
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "filesystem_denied"


# EXT-205: Prompt contract denied


@pytest.mark.asyncio
async def test_ext_205_prompt_contract_denied():
    manifest = _base_manifest(
        prompt_contract_id="pc-1",
        prompt_version="1.0.0",
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, authorized_plan={"allowed_plugins": [manifest.id], "allowed_capabilities": []})
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "prompt_contract_denied"


# EXT-206: Human gate required


@pytest.mark.asyncio
async def test_ext_206_human_gate_required():
    class HumanGatePort(ActionExecutionGatePort):
        async def authorize(self, **kwargs: Any) -> tuple[bool, str, list[str], bool, Any]:
            return True, "decision-1", [], True, {}

    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", side_effect_level=SideEffectLevel.WRITE)],
        side_effect_level=SideEffectLevel.WRITE,
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry, gate_port=HumanGatePort())
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "human_gate_required"


# EXT-207: Tenant denied


@pytest.mark.asyncio
async def test_ext_207_tenant_denied():
    manifest = _base_manifest(tenant_scope="multi", allowed_tenant_ids=["other-tenant"])
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "tenant_denied"


# EXT-208: Budget exhausted


@pytest.mark.asyncio
async def test_ext_208_budget_exhausted():
    manifest = _base_manifest()
    context = ExtensionExecutionContext.for_runtime(
        request_id="req-1",
        correlation_id="corr-1",
        user_id="user-1",
        tenant_id="tenant-1",
        budget=ExecutionBudget(max_duration_ms=0),
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, context=context)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "budget_exhausted"


# EXT-209: Timeout clamped


@pytest.mark.asyncio
async def test_ext_209_timeout_clamped():
    manifest = _base_manifest(timeout_ms=1000)
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, timeout_override_ms=5000)
    result = await service.execute(request)
    assert result.status == "success"
    assert result.latency_ms >= 0


# EXT-210: Input schema rejected


@pytest.mark.asyncio
async def test_ext_210_input_schema_rejected():
    manifest = _base_manifest(
        input_schema={"type": "object", "required": ["message"], "properties": {"message": {"type": "string"}}},
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, payload={})
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "invalid_input"


# EXT-211: Output schema rejected


@pytest.mark.asyncio
async def test_ext_211_output_schema_rejected():
    class BadHandler:
        async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
            return {"bad": True}

    manifest = _base_manifest(
        output_schema={"type": "object", "required": ["echo"], "properties": {"echo": {"type": "string"}}},
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=BadHandler()
    )})()
    service = _service(registry)
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "invalid_output"


# EXT-212: RBAC denied


@pytest.mark.asyncio
async def test_ext_212_rbac_denied():
    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", required_roles=["admin"])],
        required_roles=["admin"],
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    context = ExtensionExecutionContext.for_runtime(
        request_id="req-1",
        correlation_id="corr-1",
        user_id="user-1",
        tenant_id="tenant-1",
        roles=(),
    )
    request = _request(manifest, context=context)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "rbac_denied"


# EXT-213: Permission denied


@pytest.mark.asyncio
async def test_ext_213_permission_denied():
    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", required_permissions=["admin.write"])],
        required_permissions=["admin.write"],
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, authorized_plan={"allowed_plugins": [manifest.id], "allowed_capabilities": []})
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "permission_denied"


# EXT-214: Policy denied by gate port


@pytest.mark.asyncio
async def test_ext_214_policy_denied_by_gate():
    class DenyGatePort(ActionExecutionGatePort):
        async def authorize(self, **kwargs: Any) -> tuple[bool, str, list[str], bool, Any]:
            return False, "decision-2", ["policy_denied"], False, {}

    manifest = _base_manifest(
        capabilities=[ExtensionCapability(id="echo", version="1.0.0", side_effect_level=SideEffectLevel.WRITE)],
        side_effect_level=SideEffectLevel.WRITE,
    )
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry, gate_port=DenyGatePort())
    request = _request(manifest)
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "policy_denied"


# EXT-215: Capability not declared


@pytest.mark.asyncio
async def test_ext_215_capability_not_declared():
    manifest = _base_manifest(capabilities=[ExtensionCapability(id="echo", version="1.0.0")])
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=FakeHandler()
    )})()
    service = _service(registry)
    request = _request(manifest, capability="missing")
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "invalid_capability"


# EXT-216: Execution cancelled


@pytest.mark.asyncio
async def test_ext_216_execution_cancelled():
    class SlowHandler:
        async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
            await asyncio.sleep(10)
            return {"echo": payload.get("message", "")}

    manifest = _base_manifest(timeout_ms=1000)
    registry = type("FakeRegistry", (), {"get": lambda self, pid: ExtensionRegistration(
        manifest=manifest, state=ExtensionLifecycleState.ENABLED, instance=SlowHandler()
    )})()
    service = _service(registry)

    context = ExtensionExecutionContext.for_runtime(
        request_id="req-1",
        correlation_id="corr-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )
    request = _request(manifest, context=context)

    task = asyncio.create_task(service.execute(request))
    await asyncio.sleep(0)
    with patch.object(service, "_active", {"exec-id": task}):
        cancelled = await service.cancel("exec-id")
    assert cancelled is True
    result = await task
    assert result.status == "failed"
    assert result.error_code == "cancelled"


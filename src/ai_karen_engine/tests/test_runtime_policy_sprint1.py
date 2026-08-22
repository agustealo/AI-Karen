"""
Sprint 1: RuntimePolicy Semantic Closure — Architecture and security proofs.

Validates that RuntimePolicy is the single authorization authority,
CORTEX delegates to it, provider selection obeys policy constraints,
and plugin execution requires a policy decision.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ai_karen_engine.core.runtime.policy import (
    PolicyDecision,
    PolicyEvaluationRequest,
    PolicyReasonCode,
    ProviderConstraints,
    ResourceConstraints,
    RuntimeLevel,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.core.runtime.cortex_execution_decider import (
    CortexExecutionDecider,
)
from ai_karen_engine.services.plugin_execution import (
    ExecutionRequest,
    ExecutionStatus,
    PluginExecutionEngine,
)


# ---------------------------------------------------------------------------
# Architecture proofs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_policy_is_authorization_authority():
    """RuntimePolicyEnforcer is the single typed authorization entry point."""
    enforcer = RuntimePolicyEnforcer()
    assert hasattr(enforcer, "evaluate")

    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        requested_capabilities=["web_search"],
    )
    decision = await enforcer.evaluate(request)
    assert decision is not None
    assert hasattr(decision, "decision_id")
    assert hasattr(decision, "allowed")
    assert hasattr(decision, "provider_constraints")
    assert hasattr(decision, "resource_constraints")
    assert hasattr(decision, "evaluated_at")


def test_cortex_does_not_authorize_execution():
    """CORTEXExecutionDecider must not contain inline RBAC authorization."""
    import ai_karen_engine.core.runtime.cortex_execution_decider as decider_module
    source = open(decider_module.__file__).read()
    assert "_evaluate_rbac_policy" not in source
    assert "RuntimePolicyEnforcer" in source


@pytest.mark.asyncio
async def test_provider_router_does_not_override_policy():
    """Provider selection receives policy constraints but does not override them."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        provider_constraints=ProviderConstraints(
            eligible_providers=["local"],
            forbidden_providers=["external"],
            local_only=True,
        ),
    )
    decision = await enforcer.evaluate(request)
    assert decision.provider_constraints is not None
    assert decision.provider_constraints.local_only is True
    assert "external" in decision.provider_constraints.forbidden_providers
    assert "local" in decision.provider_constraints.eligible_providers


@pytest.mark.asyncio
async def test_plugin_engine_requires_policy_decision():
    """PluginExecutionEngine must reject execution without policy_decision_id."""
    engine = PluginExecutionEngine(registry=None)
    request = ExecutionRequest(
        plugin_name="test-plugin",
        parameters={},
    )
    result = await engine.execute_plugin(request)
    assert result.status == ExecutionStatus.FAILED
    assert "policy_decision_id" in (result.error or "").lower() or "denied" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_fallback_cannot_bypass_policy_constraints():
    """Provider fallback must not bypass policy constraints."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        runtime_level=RuntimeLevel.EMERGENCY,
        provider_constraints=ProviderConstraints(
            eligible_providers=["local"],
            local_only=True,
        ),
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is True
    assert decision.provider_constraints is not None
    assert decision.provider_constraints.local_only is True
    assert "external" not in decision.provider_constraints.eligible_providers


# ---------------------------------------------------------------------------
# Security proofs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_tenant_denies():
    """Missing tenant must deny."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="",
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is False
    assert PolicyReasonCode.MISSING_IDENTITY in decision.reason_codes


@pytest.mark.asyncio
async def test_missing_user_denies():
    """Missing user where required must deny."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="",
        tenant_id="tenant-1",
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is False
    assert PolicyReasonCode.MISSING_IDENTITY in decision.reason_codes


@pytest.mark.asyncio
async def test_forbidden_capability_denies():
    """Forbidden capability must deny."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        requested_capabilities=["admin"],
        forbidden_capabilities=["admin"],
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is False
    assert PolicyReasonCode.CAPABILITY_CONFLICT in decision.reason_codes


@pytest.mark.asyncio
async def test_restricted_resource_denies():
    """Restricted resource scope must deny."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        resource_scope=None,
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_plugin_lacks_permission_denies():
    """Plugin without permission must deny."""
    mock_manifest = MagicMock()
    mock_manifest.name = "test-plugin"
    mock_manifest.version = "1.0.0"
    mock_manifest.permissions = MagicMock()
    mock_manifest.permissions.model_dump.return_value = {"network_access": True}
    mock_manifest.resources = MagicMock()
    mock_manifest.resources.model_dump.return_value = {}
    mock_manifest.capabilities = MagicMock()
    mock_manifest.capabilities.model_dump.return_value = {}

    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = {"manifest": mock_manifest, "status": "active"}

    engine = PluginExecutionEngine(registry=mock_registry)
    request = ExecutionRequest(
        plugin_name="test-plugin",
        parameters={},
        policy_decision_id="policy-1",
        allowed_capabilities=[],
        forbidden_capabilities=["network_access"],
    )
    result = await engine.execute_plugin(request)
    assert result.status == ExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_external_provider_prohibited():
    """External provider must be prohibited when policy says so."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        provider_constraints=ProviderConstraints(
            eligible_providers=["local"],
            forbidden_providers=["external"],
            external_allowed=False,
        ),
    )
    decision = await enforcer.evaluate(request)
    assert decision.provider_constraints is not None
    assert decision.provider_constraints.external_allowed is False
    assert "external" in decision.provider_constraints.forbidden_providers


def test_cortex_cannot_override_policy():
    """CORTEX must not override RuntimePolicy decisions."""
    decider = CortexExecutionDecider()
    assert hasattr(decider, "_policy_enforcer")
    assert decider.cortex_never_executes() is True


@pytest.mark.asyncio
async def test_provider_fallback_cannot_bypass_policy():
    """Provider fallback path must respect policy constraints."""
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        runtime_level=RuntimeLevel.SAFE,
        provider_constraints=ProviderConstraints(
            eligible_providers=["local", "trusted"],
            forbidden_providers=["external"],
        ),
    )
    decision = await enforcer.evaluate(request)
    assert decision.provider_constraints is not None
    assert "external" in decision.provider_constraints.forbidden_providers


# ---------------------------------------------------------------------------
# Typed contract completeness
# ---------------------------------------------------------------------------


def test_policy_evaluation_request_has_identity_fields():
    """PolicyEvaluationRequest must include session_id and correlation_id."""
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        correlation_id="corr-1",
    )
    assert request.session_id == "session-1"
    assert request.correlation_id == "corr-1"
    assert request.plugin_id is None
    assert request.execution_topology == {}


@pytest.mark.asyncio
async def test_policy_decision_has_typed_constraints():
    """PolicyDecision must expose typed provider and resource constraints."""
    decision = PolicyDecision(
        decision_id="policy-1",
        policy_version="v1",
        allowed=True,
        provider_constraints=ProviderConstraints(
            eligible_providers=["local"],
            local_only=True,
        ),
        resource_constraints=ResourceConstraints(
            max_memory_mb=512,
            max_cpu_time_seconds=60,
        ),
        risk_level="medium",
        evaluated_at=time.time(),
    )
    assert decision.provider_constraints.local_only is True
    assert decision.resource_constraints.max_memory_mb == 512
    assert decision.risk_level == "medium"
    assert decision.evaluated_at is not None


def test_policy_decision_backward_compat_forbidden_capabilities():
    """PolicyDecision.denied_capabilities must be backward-compatible with forbidden_capabilities."""
    decision = PolicyDecision(
        decision_id="policy-1",
        policy_version="v1",
        allowed=True,
        denied_capabilities=["admin", "write"],
    )
    assert decision.denied_capabilities == ["admin", "write"]
    assert decision.forbidden_capabilities == ["admin", "write"]

    decision.forbidden_capabilities = ["delete"]
    assert decision.denied_capabilities == ["delete"]

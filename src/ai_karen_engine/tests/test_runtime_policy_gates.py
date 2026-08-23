"""
Runtime Policy Gates — Architecture boundary and security proofs.

Validates that:
- CORTEX cannot manufacture AuthorizedExecutionPlan
- ExecutionRequirements cannot authorize itself
- RuntimePolicyEnforcer is the sole policy→AuthorizedExecutionPlan owner
- RuntimePolicyEnforcer is the single typed authorization entry point
"""

from __future__ import annotations

import inspect
import os

import pytest

from ai_karen_engine.core.cortex.contracts import CortexOutput
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionRequirements
from ai_karen_engine.core.runtime.policy import (
    PolicyDecision,
    PolicyEvaluationRequest,
    PolicyReasonCode,
    ProviderConstraints,
    RuntimePolicyEnforcer,
)


# ---------------------------------------------------------------------------
# Architecture boundary proofs (RUNTIME-SPINE-1A + 1B)
# ---------------------------------------------------------------------------


def test_cortex_output_cannot_create_authorized_execution_plan():
    """CortexOutput must not be able to produce AuthorizedExecutionPlan."""
    assert not hasattr(CortexOutput, "to_authorized_plan")

    import ai_karen_engine.core.cortex.contracts as cortex_contracts
    source = inspect.getsource(cortex_contracts)
    assert "AuthorizedExecutionPlan" not in source


def test_execution_requirements_cannot_authorize():
    """ExecutionRequirements must not authorize itself."""
    assert not hasattr(ExecutionRequirements, "authorize")
    assert not hasattr(ExecutionRequirements, "to_authorized_plan")

    import ai_karen_engine.core.runtime.contracts as runtime_contracts
    source = inspect.getsource(runtime_contracts)
    assert "RuntimePolicyEnforcer" not in source


def test_runtime_policy_enforcer_is_only_authorization_owner():
    """RuntimePolicyEnforcer (via PolicyDecision) is the sole AuthorizedExecutionPlan owner."""
    import ai_karen_engine.core.runtime.policy.runtime_policy as policy_module
    source = inspect.getsource(policy_module)
    assert "def to_authorized_plan" in source

    assert not os.path.exists(
        os.path.join(
            os.path.dirname(policy_module.__file__),
            "..",
            "cortex",
            "runtime_policy.py",
        )
    )


def test_cortex_runtime_policy_module_removed():
    """core/cortex/runtime_policy.py must not exist."""
    import ai_karen_engine.core.cortex as cortex_pkg
    cortex_dir = os.path.dirname(cortex_pkg.__file__)
    assert not os.path.exists(os.path.join(cortex_dir, "runtime_policy.py"))


@pytest.mark.asyncio
async def test_runtime_policy_enforcer_is_authorization_authority():
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


def test_policy_decision_to_authorized_plan_is_unique_owner():
    """Only PolicyDecision.to_authorized_plan may create AuthorizedExecutionPlan from policy."""
    plan = PolicyDecision(
        decision_id="policy-1",
        policy_version="v1",
        allowed=True,
    ).to_authorized_plan()
    assert isinstance(plan, AuthorizedExecutionPlan)
    assert plan.execution_id == "policy-1"
    assert plan.policy_decision_id == "policy-1"


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

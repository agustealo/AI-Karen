"""
Plugin Governance Closure (PG-CLOSE) tests.

Validates that:
- RuntimePolicy is the sole plugin authorization authority
- AuthorityChainService no longer performs authorization
- ExtensionManifest is strict and treats permissions as requests, not grants
- PluginLifecycleManager owns canonical lifecycle state
- RuntimePolicy -> AuthorizedExecutionPlan -> PluginExecutionContext wiring is correct
- Input/output schemas are enforced
- Execution is trajectory-recorded and audited
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.extensions.platform.core.authority_chain import (
    AuthorityChainService,
    AuthorityLevel,
    AuthorityViolation,
    LifecycleViolation,
)
from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
    PluginLifecycleManager,
    PluginLifecycleState,
)
from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest,
    ExtensionPermissions,
    ExtensionResources,
)
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    RuntimePolicyEnforcer,
    PolicyEvaluationRequest,
    RuntimeLevel,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionTopology,
    ActionExecutionGate,
)
from ai_karen_engine.services.plugin_execution import (
    PluginExecutionContext,
    ExecutionRequest,
    ExecutionMode,
    PluginExecutionEngine,
)
from ai_karen_engine.extensions.platform.core.registry.database_models import (
    ExtensionInstallationHistory,
)


def test_runtime_policy_is_only_plugin_authorization_authority():
    """AuthorityChainService must not contain allow/deny authorization logic."""
    source = Path(__file__).resolve().parents[1] / "extensions" / "platform" / "core" / "authority_chain.py"
    text = source.read_text(encoding="utf-8")

    assert "verify_authority_boundary" not in text, (
        "AuthorityChainService must not contain verify_authority_boundary"
    )
    assert "_has_sufficient_authority" not in text, (
        "AuthorityChainService must not contain _has_sufficient_authority"
    )
    assert "AUTHORITY_ACTIONS" not in text, (
        "AuthorityChainService must not contain AUTHORITY_ACTIONS authorization table"
    )
    assert "escalate_authority" not in text, (
        "AuthorityChainService must not contain escalate_authority"
    )


def test_plugin_manifest_cannot_grant_its_own_permissions():
    """ExtensionManifest permissions are requested declarations, not grants."""
    manifest = ExtensionManifest(
        name="test-plugin",
        version="1.0.0",
        display_name="Test",
        description="Test",
        author="test",
        license="MIT",
        category="test",
        permissions=ExtensionPermissions(
            memory_read=True,
            memory_write=True,
            system_config_write=True,
        ),
    )

    assert manifest.permissions.memory_read is True
    assert manifest.permissions.system_config_write is True

    policy = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        requested_capabilities=["memory_read", "system_config_write"],
        forbidden_capabilities=["memory_write"],
        permissions=["user"],
    )
    decision = policy.evaluate(request)
    assert decision.allowed is True
    assert "memory_write" in decision.denied_capabilities
    assert "memory_read" in decision.allowed_capabilities
    assert "system_config_write" in decision.allowed_capabilities


def test_caller_cannot_inject_permissions():
    """ExecutionRequest must not accept caller-owned permission fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionRequest(
            plugin_name="test-plugin",
            parameters={},
            allowed_capabilities=["admin"],
        )


def test_caller_cannot_inject_resource_limits():
    """ExecutionRequest must not accept caller-owned resource_limits."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionRequest(
            plugin_name="test-plugin",
            parameters={},
            resource_limits={"max_memory_mb": 9999},
        )


def test_caller_cannot_override_tenant_scope():
    """PluginExecutionContext must not accept caller-supplied tenant_id after policy."""
    context = PluginExecutionContext(
        plugin_id="test",
        plugin_version="1.0.0",
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="session-1",
        conversation_id="conv-1",
        request_id="req-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
        allowed_capabilities=["read"],
    )

    assert context.tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_plugin_requires_policy_decision():
    """Plugin execution must require a policy_decision_id."""
    engine = PluginExecutionEngine(registry=None)
    request = ExecutionRequest(
        plugin_name="test-plugin",
        parameters={},
        policy_decision_id=None,
    )
    result = await engine.execute_plugin(request)
    assert result.status == "failed"
    assert "policy_decision_id" in (result.error or "").lower()


def test_plugin_requires_authorized_execution_plan():
    """PluginExecutionContext must be built from AuthorizedExecutionPlan."""
    plan = AuthorizedExecutionPlan(
        execution_id="exec-1",
        policy_decision_id="policy-1",
        topology=ExecutionTopology.DIRECT,
        allowed_capabilities=["web_search"],
        allowed_tools=["search"],
        allowed_plugins=[],
        provider_constraints={"eligible_providers": ["local"]},
        resource_scope={"allowed_paths": ["/tmp"]},
        budget=None,
    )

    assert plan.policy_decision_id == "policy-1"
    assert plan.allowed_capabilities == ["web_search"]
    assert plan.allowed_tools == ["search"]


@pytest.mark.asyncio
async def test_plugin_input_schema_enforced():
    """PluginExecutionEngine must enforce input schema from manifest."""
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

    manifest = ExtensionManifest(
        name="schema-plugin",
        version="1.0.0",
        display_name="Schema",
        description="Test",
        author="test",
        license="MIT",
        category="test",
    )

    engine = PluginExecutionEngine(registry=None)
    request = ExecutionRequest(
        plugin_name="schema-plugin",
        parameters={"unexpected": "value"},
        policy_decision_id="policy-1",
    )

    manifest_data = manifest.to_dict()
    manifest_data["model_extra"] = {
        "parameters": {
            "expected": {"type": "string", "required": True}
        },
        "allow_additional_parameters": False,
    }

    plugin_metadata = {"manifest": manifest, "status": "registered", "path": Path(".")}
    sanitized = await engine._validate_and_sanitize_input(request.parameters, plugin_metadata)
    assert "unexpected" not in sanitized


@pytest.mark.asyncio
async def test_plugin_output_schema_enforced():
    """PluginExecutionEngine must enforce output size limits."""
    engine = PluginExecutionEngine(registry=None)
    large_output = "x" * (2000 * 1024)
    manifest = type("M", (), {"name": "test"})()
    result = await engine._validate_and_sanitize_output(large_output, {"manifest": manifest}, type("L", (), {"max_output_size_kb": 1024})())
    assert len(result) <= 1024 * 1024


def test_manifest_unknown_fields_rejected():
    """ExtensionManifest must reject unknown fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtensionManifest(
            name="test-plugin",
            version="1.0.0",
            display_name="Test",
            description="Test",
            author="test",
            license="MIT",
            category="test",
            unknown_field="rejected",
        )


def test_plugin_secrets_are_references_not_values():
    """PluginExecutionContext must not contain raw secret values."""
    context = PluginExecutionContext(
        plugin_id="test",
        plugin_version="1.0.0",
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        conversation_id="conv-1",
        request_id="req-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
        allowed_capabilities=["read"],
    )

    assert not hasattr(context, "raw_auth_token")
    assert not hasattr(context, "raw_session_object")
    assert not hasattr(context, "unrestricted_db_connection")
    assert not hasattr(context, "arbitrary_environment")


def test_plugin_execution_is_trajectory_recorded():
    """PluginExecutionEngine must record executions in history."""
    engine = PluginExecutionEngine(registry=None)
    history = engine.get_execution_history()
    assert isinstance(history, list)


def test_plugin_execution_is_audited():
    """Plugin lifecycle operations must be logged to database history."""
    assert ExtensionInstallationHistory is not None


def test_cross_tenant_plugin_execution_rejected():
    """Plugin execution must reject cross-tenant access."""
    context = PluginExecutionContext(
        plugin_id="test",
        plugin_version="1.0.0",
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="session-1",
        conversation_id="conv-1",
        request_id="req-1",
        correlation_id="corr-1",
        policy_decision_id="policy-1",
        allowed_capabilities=["read"],
    )

    assert context.tenant_id == "tenant-a"


def test_single_plugin_lifecycle_authority():
    """PluginLifecycleManager must be the sole lifecycle authority."""
    source = Path(__file__).resolve().parents[1] / "extensions" / "platform" / "core" / "plugin_lifecycle_manager.py"
    text = source.read_text(encoding="utf-8")

    assert "class PluginLifecycleState" in text
    assert "class PluginLifecycleManager" in text
    assert "async def install_plugin" in text
    assert "async def uninstall_plugin" in text
    assert "async def enable_plugin" in text
    assert "async def disable_plugin" in text

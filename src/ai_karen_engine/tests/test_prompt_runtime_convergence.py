"""
Architecture proof tests for RC1.5 PromptRuntime convergence.

Validates:
- PromptRegistry is a true singleton
- PromptAssembler uses the canonical registry
- PromptRegistry is version-aware
- Canonical prompt contracts are registered
"""

from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.prompt.prompt_assembler import (
    PromptAssembler,
    PromptDefinition,
    PromptRegistry,
    get_prompt_assembler,
    get_prompt_registry,
    register_default_prompts,
)


def test_prompt_registry_is_singleton() -> None:
    """get_prompt_registry() must always return the same instance."""
    registry_a = get_prompt_registry()
    registry_b = get_prompt_registry()
    assert registry_a is registry_b


def test_prompt_assembler_uses_canonical_registry() -> None:
    """PromptAssembler must use the canonical PromptRegistry by default."""
    assembler = get_prompt_assembler()
    assert assembler.registry is get_prompt_registry()


def test_plugin_validator_and_assembler_share_registry() -> None:
    """Plugin validator and assembler must share the same PromptRegistry."""
    from ai_karen_engine.extensions.platform.core.registry.validator import (
        ExtensionValidator,
    )
    from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

    registry = get_prompt_registry()
    register_default_prompts(registry)

    validator = ExtensionValidator()
    manifest = ExtensionManifest(
        name="registry-share-test",
        version="1.0.0",
        display_name="Registry Share Test",
        description="Test",
        author="test",
        license="MIT",
        category="integration",
        prompt_files={
            "contract_id": "karen.chat.default@v1",
            "mode": "custom",
            "prompt_first": True,
        },
    )

    is_valid, errors, warnings = validator.validate_manifest(manifest)
    assert is_valid is True
    assert not errors


def test_registered_contract_resolves_during_actual_assembly() -> None:
    """A registered prompt contract must resolve during actual assembly."""
    import asyncio

    registry = get_prompt_registry()
    register_default_prompts(registry)

    assembler = PromptAssembler(registry=registry)
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        prompt_version="v1",
        messages=[{"role": "user", "content": "Hello"}],
    )
    result = asyncio.get_event_loop().run_until_complete(assembler.assemble(request))
    assert result.prompt_id == "karen.chat.default"
    assert result.prompt_version == "v1"


def test_no_secondary_prompt_registry_instances() -> None:
    """There must be exactly one PromptRegistry instance from the canonical getter."""
    registry = get_prompt_registry()
    register_default_prompts(registry)
    assert registry.get("karen.chat.default", "v1") is not None


def test_multiple_prompt_versions_coexist() -> None:
    """Multiple versions of the same prompt_id must coexist without overwriting."""
    registry = PromptRegistry()
    registry.register(
        PromptDefinition(
            prompt_id="karen.chat.default",
            version="v1",
            name="Default v1",
            description="First version",
            token_budget=4096,
        )
    )
    registry.register(
        PromptDefinition(
            prompt_id="karen.chat.default",
            version="v2",
            name="Default v2",
            description="Second version",
            token_budget=8192,
        )
    )

    v1 = registry.get("karen.chat.default", "v1")
    v2 = registry.get("karen.chat.default", "v2")
    latest = registry.get("karen.chat.default")

    assert v1 is not None
    assert v2 is not None
    assert latest is not None
    assert v1.version == "v1"
    assert v2.version == "v2"
    assert latest.version == "v2"


def test_exact_prompt_version_resolution() -> None:
    """Exact version resolution must return the requested version."""
    registry = PromptRegistry()
    registry.register(
        PromptDefinition(
            prompt_id="karen.chat.reasoning",
            version="v1",
            name="Reasoning v1",
            description="First version",
            token_budget=4096,
        )
    )

    resolved = registry.get("karen.chat.reasoning", "v1")
    assert resolved is not None
    assert resolved.version == "v1"


def test_unknown_version_fails_closed() -> None:
    """Requesting an unknown version must return None."""
    registry = PromptRegistry()
    registry.register(
        PromptDefinition(
            prompt_id="karen.chat.default",
            version="v1",
            name="Default v1",
            description="First version",
            token_budget=4096,
        )
    )

    assert registry.get("karen.chat.default", "v99") is None
    assert registry.get("does-not-exist", "v1") is None


def test_prompt_registry_registration_and_list() -> None:
    """Registered prompts must be listable and retrievable."""
    registry = PromptRegistry()
    definition = PromptDefinition(
        prompt_id="karen.tool.use",
        version="v1",
        name="Tool Use v1",
        description="Tool use contract",
        token_budget=4096,
    )
    registry.register(definition)

    assert registry.get("karen.tool.use", "v1") is definition
    assert definition in registry.list_definitions()


def test_prompt_definition_affects_assembly() -> None:
    """Resolved PromptDefinition must contribute defaults to assembly."""
    import asyncio

    registry = PromptRegistry()
    definition = PromptDefinition(
        prompt_id="karen.chat.default",
        version="v1",
        name="Default",
        description="Default contract",
        system_prompt="Default system prompt from contract.",
        token_budget=2048,
        tool_contracts=[{"name": "contract_tool", "description": "From contract"}],
        output_schema={"format": "json"},
    )
    registry.register(definition)

    assembler = PromptAssembler(registry=registry)
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        prompt_version="v1",
        messages=[{"role": "user", "content": "Hello"}],
        tool_contracts=[{"name": "request_tool", "description": "From request"}],
    )
    result = asyncio.get_event_loop().run_until_complete(assembler.assemble(request))

    assert result.metadata.get("registry_lookup") is True
    assert result.metadata.get("prompt_contract_id") == "karen.chat.default"
    assert any("Default system prompt from contract." in msg.get("content", "") for msg in result.messages)
    assert "contract_tool" in result.included_tool_contracts
    assert "request_tool" in result.included_tool_contracts


def test_assembly_respects_token_budget() -> None:
    """Assembly must respect token budget and emit truncation events."""
    import asyncio

    registry = PromptRegistry()
    definition = PromptDefinition(
        prompt_id="karen.chat.default",
        version="v1",
        name="Default",
        description="Default contract",
        system_prompt="System prompt.",
        token_budget=50,
    )
    registry.register(definition)

    assembler = PromptAssembler(registry=registry)
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        prompt_version="v1",
        token_budget=50,
        messages=[{"role": "user", "content": "Hello " * 200}],
        memory_items=[{"id": "m1", "content": "Memory " * 200}],
        tool_contracts=[{"name": "tool", "description": "Tool " * 200}],
    )
    result = asyncio.get_event_loop().run_until_complete(assembler.assemble(request))

    assert result.token_estimate <= 50
    assert result.truncation_events


def test_policy_sections_are_protected_from_truncation() -> None:
    """System policy and output contract should be protected from truncation."""
    import asyncio

    registry = PromptRegistry()
    definition = PromptDefinition(
        prompt_id="karen.chat.default",
        version="v1",
        name="Default",
        description="Default contract",
        system_prompt="Protected system policy.",
        output_schema={"format": "json"},
        token_budget=100,
    )
    registry.register(definition)

    assembler = PromptAssembler(registry=registry)
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        prompt_version="v1",
        system_policy="Protected system policy.",
        output_schema={"format": "json"},
        token_budget=100,
        messages=[{"role": "user", "content": "Hello"}],
        memory_items=[{"id": "m1", "content": "Memory " * 200}],
    )
    result = asyncio.get_event_loop().run_until_complete(assembler.assemble(request))

    contents = " ".join(msg.get("content", "") for msg in result.messages)
    assert "Protected system policy." in contents
    assert "format=json" in contents


def test_wired_request_fields_appear_in_assembly() -> None:
    """Wired PromptAssemblyRequest fields must appear in assembled output."""
    import asyncio

    registry = PromptRegistry()
    register_default_prompts(registry)

    assembler = PromptAssembler(registry=registry)
    request = PromptAssemblyRequest(
        prompt_id="karen.chat.default",
        prompt_version="v1",
        system_policy="System policy",
        tenant_policy="Tenant policy",
        persona={"system_prompt": "Persona prompt"},
        profile={"style": "concise"},
        cortex_intent={"intent": "research", "intent_confidence": 0.9},
        tool_contracts=[{"name": "search", "description": "Search tool"}],
        workflow_context={"workflow_id": "wf-1", "objective": "Research"},
        provider_capabilities={"format": "json"},
        output_schema={"type": "object"},
        token_budget=4096,
        messages=[{"role": "user", "content": "Hello"}],
    )
    result = asyncio.get_event_loop().run_until_complete(assembler.assemble(request))

    contents = " ".join(msg.get("content", "") for msg in result.messages)
    assert "System policy" in contents
    assert "Tenant policy" in contents
    assert "Persona prompt" in contents
    assert "intent=research" in contents
    assert "search" in contents
    assert "workflow_id=wf-1" in contents
    assert "format=json" in contents


def test_runtime_policy_uses_capabilities_not_intent_strings() -> None:
    """RuntimePolicy must evaluate typed capabilities, not hardcoded intent strings."""
    import asyncio
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer, PolicyEvaluationRequest

    enforcer = RuntimePolicyEnforcer()

    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        permissions=["user"],
        requested_capabilities=["write"],
        forbidden_capabilities=[],
        risk_signals={"score": 0.0, "categories": []},
        runtime_level="FULL",
    )
    decision = asyncio.get_event_loop().run_until_complete(enforcer.evaluate(request))
    assert decision.allowed is True
    assert "write" in decision.allowed_capabilities


def test_runtime_policy_denies_on_risk_categories() -> None:
    """RuntimePolicy must deny high-risk capability combinations based on risk_signals."""
    import asyncio
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer, PolicyEvaluationRequest

    enforcer = RuntimePolicyEnforcer()

    request = PolicyEvaluationRequest(
        user_id="user-1",
        tenant_id="tenant-1",
        permissions=["user"],
        requested_capabilities=["admin"],
        forbidden_capabilities=[],
        risk_signals={"score": 0.8, "categories": ["credential_access"]},
        runtime_level="FULL",
    )
    decision = asyncio.get_event_loop().run_until_complete(enforcer.evaluate(request))
    assert decision.allowed is False
    assert "admin" in decision.forbidden_capabilities


def test_runtime_policy_rejects_missing_identity() -> None:
    """RuntimePolicy must fail-closed when identity is missing."""
    import asyncio
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer, PolicyEvaluationRequest

    enforcer = RuntimePolicyEnforcer()

    request = PolicyEvaluationRequest(
        user_id="",
        tenant_id="",
        requested_capabilities=[],
    )
    decision = asyncio.get_event_loop().run_until_complete(enforcer.evaluate(request))
    assert decision.allowed is False
    assert "all" in decision.forbidden_capabilities


def test_runtime_policy_uses_provider_constraints_not_hardcoded_list() -> None:
    """Routing policy must use provider constraints from state, not hardcoded provider lists."""
    import asyncio
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer

    enforcer = RuntimePolicyEnforcer()

    state = {
        "runtime_level": "SAFE",
        "provider_constraints": {
            "safe_trusted_providers": ["trusted-provider"]
        },
    }
    provider_selection = {"provider": "trusted-provider", "model": "model-x"}
    result = asyncio.get_event_loop().run_until_complete(
        enforcer.check_routing_policy(state, provider_selection)
    )
    assert result.allowed is True

    provider_selection_denied = {"provider": "untrusted-provider", "model": "model-x"}
    result = asyncio.get_event_loop().run_until_complete(
        enforcer.check_routing_policy(state, provider_selection_denied)
    )
    assert result.allowed is False


def test_response_policy_has_no_keyword_safety_logic() -> None:
    """Response policy must not block based on weak keyword scanning."""
    import asyncio
    from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer

    enforcer = RuntimePolicyEnforcer()

    state = {"runtime_level": "SAFE"}
    response = "Here is how to delete a file safely."
    result = asyncio.get_event_loop().run_until_complete(
        enforcer.check_response_policy(state, response)
    )
    assert result.allowed is True


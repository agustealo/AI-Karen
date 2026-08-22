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

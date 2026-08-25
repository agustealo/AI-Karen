import pytest

from ai_karen_engine.core.ai_runtime.capability_registry import CapabilityRegistry
from ai_karen_engine.core.ai_runtime.capability_types import (
    CapabilityDefinition,
    CapabilityId,
)


def test_register_and_get_capability() -> None:
    registry = CapabilityRegistry()
    capability = CapabilityDefinition(
        id=CapabilityId.CHAT_GENERATE,
        name="Chat Generation",
        description="Generate chat responses.",
        required_inputs=("messages",),
    )

    registry.register(capability)

    result = registry.get(CapabilityId.CHAT_GENERATE)
    assert result.found is True
    assert result.capability == capability


def test_duplicate_register_raises() -> None:
    registry = CapabilityRegistry()
    capability = CapabilityDefinition(
        id=CapabilityId.TEXT_GENERATE,
        name="Text Generation",
        description="Generate text.",
    )

    registry.register(capability)

    with pytest.raises(ValueError):
        registry.register(capability)


def test_upsert_replaces_existing_capability() -> None:
    registry = CapabilityRegistry()

    original = CapabilityDefinition(
        id=CapabilityId.TEXT_SUMMARIZE,
        name="Summarize",
        description="Old description.",
    )
    updated = CapabilityDefinition(
        id=CapabilityId.TEXT_SUMMARIZE,
        name="Summarize",
        description="New description.",
    )

    registry.upsert(original)
    registry.upsert(updated)

    result = registry.require(CapabilityId.TEXT_SUMMARIZE)
    assert result.description == "New description."


def test_unknown_capability_returns_lookup_result() -> None:
    registry = CapabilityRegistry()

    result = registry.get(CapabilityId.MEMORY_SCORE)

    assert result.found is False
    assert result.capability is None
    assert result.reason == "capability_not_registered"


def test_provider_ids_are_not_capability_ids() -> None:
    registry = CapabilityRegistry()

    with pytest.raises(ValueError):
        registry.get("gemini")

    with pytest.raises(ValueError):
        registry.get("builtin_vllm")
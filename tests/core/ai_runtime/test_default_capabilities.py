from ai_karen_engine.core.ai_runtime.capability_registry import CapabilityRegistry
from ai_karen_engine.core.ai_runtime.capability_types import CapabilityId
from ai_karen_engine.core.ai_runtime.default_capabilities import (
    DEFAULT_CAPABILITY_DEFINITIONS,
    register_default_capabilities,
)


def test_default_capabilities_are_unique() -> None:
    ids = [item.id for item in DEFAULT_CAPABILITY_DEFINITIONS]
    assert len(ids) == len(set(ids))


def test_register_default_capabilities() -> None:
    registry = CapabilityRegistry()

    register_default_capabilities(registry)

    ids = set(registry.ids())
    assert CapabilityId.CHAT_GENERATE.value in ids
    assert CapabilityId.TEXT_EMBED.value in ids
    assert CapabilityId.INTENT_CLASSIFY.value in ids
    assert CapabilityId.MEMORY_SCORE.value in ids
    assert CapabilityId.SAFETY_CLASSIFY.value in ids


def test_default_capabilities_do_not_register_providers() -> None:
    registry = CapabilityRegistry()

    register_default_capabilities(registry)

    ids = set(registry.ids())
    assert "openai" not in ids
    assert "gemini" not in ids
    assert "ollama" not in ids
    assert "builtin_vllm" not in ids
    assert "builtin_transformers" not in ids
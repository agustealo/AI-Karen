"""Backward-compatible Persona Studio preference contract tests."""

import pytest

from ai_karen_engine.core.persona.contracts import (
    ChatStyleContext,
    ToneEnum,
    UserPersonaPreferences,
    VerbosityEnum,
)


def make_preferences(**extras):
    return UserPersonaPreferences(
        "user-id", "assistant",
        ChatStyleContext(ToneEnum.FRIENDLY, VerbosityEnum.MODERATE),
        "2026-10-24", "2026-10-24", None,
        **extras,
    )


def test_legacy_positional_constructor_remains_compatible():
    result = make_preferences()
    assert result.preferred_persona_id == "assistant"
    assert result.revision == 0
    assert result.tenant_id is None
    assert result.cross_persona_memory_sharing is False
    assert result.enable_persona_memory_filtering is False


def test_additive_persona_preferences_preserve_explicit_scope_and_revision():
    result = make_preferences(
        tenant_id="tenant-id", revision=4,
        enable_style_adaptation=True,
        enable_persona_memory_filtering=True,
    )
    assert (result.tenant_id, result.revision) == ("tenant-id", 4)
    assert result.enable_style_adaptation is True
    assert result.cross_persona_memory_sharing is False


@pytest.mark.parametrize("revision", [-1, True, 1.5, "1"])
def test_invalid_revision_fails_closed(revision):
    with pytest.raises(ValueError, match="revision"):
        make_preferences(revision=revision)


def test_blank_tenant_scope_rejected():
    with pytest.raises(ValueError, match="tenant"):
        make_preferences(tenant_id=" ")

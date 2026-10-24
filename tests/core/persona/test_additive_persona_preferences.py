"""Persona Studio contracts match the canonical tenant-scoped service."""

import pytest
from pydantic import ValidationError

from ai_karen_engine.core.persona.contracts import (
    ChatStyleContext, Persona, ToneEnum, UserPersonaPreferences, VerbosityEnum,
)


def test_tenant_scoped_preferences_have_safe_defaults():
    preferences = UserPersonaPreferences(user_id="user-id", tenant_id="tenant-id")
    assert preferences.active_persona_id is None
    assert preferences.revision == 0
    assert preferences.cross_persona_memory_sharing is False
    assert preferences.enable_persona_memory_filtering is False
    assert preferences.enable_style_adaptation is False


def test_revision_and_tenant_survive_service_style_copy():
    preferences = UserPersonaPreferences(
        user_id="user-id", tenant_id="tenant-id", revision=4,
        enable_style_adaptation=True,
    )
    updated = preferences.copy(deep=True)
    updated.active_persona_id = "assistant"
    assert updated.revision == 4
    assert updated.tenant_id == "tenant-id"
    assert preferences.active_persona_id is None


def test_persona_exposes_fields_used_by_service():
    persona = Persona(name="Expert")
    assert persona.default_tone is ToneEnum.FRIENDLY
    assert persona.default_verbosity is VerbosityEnum.BALANCED
    assert persona.dict()["name"] == "Expert"


def test_style_context_supports_persona_service_constructor():
    context = ChatStyleContext(persona=Persona(name="Helper"), turn_number=1)
    assert context.get_effective_tone() is ToneEnum.FRIENDLY


@pytest.mark.parametrize("revision", [-1, "invalid", 1.5])
def test_invalid_revisions_rejected(revision):
    with pytest.raises(ValidationError):
        UserPersonaPreferences(user_id="user-id", tenant_id="tenant-id", revision=revision)

"""Canonical persona service/API contract regression coverage."""
from ai_karen_engine.core.persona.contracts import (
    ChatStyleContext,
    Persona,
    SYSTEM_PERSONAS,
    ToneEnum,
    UserPersonaPreferences,
    VerbosityEnum,
)
from ai_karen_engine.services.persona.persona_service import PersonaService


def test_new_custom_persona_roundtrip() -> None:
    persona = Persona(name="Troy", system_prompt="Communicate as a design collaborator.")
    reconstructed = Persona(**persona.dict())
    assert reconstructed.id == persona.id
    assert reconstructed.default_tone == ToneEnum.FRIENDLY
    assert reconstructed.is_system_persona is False
    assert PersonaService._persona_payload(persona)["default_tone"] == "friendly"
    assert PersonaService._persona_payload(persona)["memory_weight"] == "medium"


def test_chat_context_respects_override_without_changing_capabilities() -> None:
    persona = Persona(name="Troy", default_tone=ToneEnum.PROFESSIONAL)
    ctx = ChatStyleContext(persona=persona)
    assert ctx.get_effective_tone() == ToneEnum.PROFESSIONAL
    assert ctx.get_effective_verbosity() == VerbosityEnum.BALANCED
    assert "Communication style" in ctx.build_system_prompt()
    assert "tool" not in ctx.build_system_prompt().lower()


def test_preferences_and_system_personas_have_usable_contracts() -> None:
    preferences = UserPersonaPreferences(user_id="alice", tenant_id="tenant-a")
    assert preferences.active_persona_id is None
    assert preferences.custom_personas == []
    assert {p.id for p in SYSTEM_PERSONAS} == {"assistant", "expert", "creative"}
    assert all(p.is_system_persona for p in SYSTEM_PERSONAS)

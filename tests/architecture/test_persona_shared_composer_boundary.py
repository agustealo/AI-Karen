"""Persona Studio must consume the existing Karen application-shell chat.

These source-level boundary checks supplement, not replace, browser continuity
and shared-session integration tests.
"""
from pathlib import Path


PERSONA_SETTINGS = Path(
    "src/ui_launchers/Karen-AI-Theme/src/components/settings/PersonaSettings.tsx"
)


def test_persona_settings_does_not_mount_a_second_conversation():
    source = PERSONA_SETTINGS.read_text(encoding="utf-8")
    forbidden = (
        "<SessionProvider",
        "<Thread",
        "<Composer",
        "<ChatRuntime",
        "new ChatRuntime(",
        "createConversation(",
    )
    assert all(token not in source for token in forbidden)


def test_persona_activation_stays_in_backend_preferences_contract():
    source = PERSONA_SETTINGS.read_text(encoding="utf-8")
    assert "PERSONA_PREFERENCES_ENDPOINT" in source
    assert "expected_revision: personaRevision" in source
    assert "setPersonaRevision(selected.revision)" in source
    assert "setPersonaRevision(null)" in source

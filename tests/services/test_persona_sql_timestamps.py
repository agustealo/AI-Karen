"""Persona SQL timestamp compatibility regression."""
from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.persona.contracts import Persona
from ai_karen_engine.services.persona.persona_service import PersonaService


def test_legacy_timestamp_column_receives_naive_utc():
    eastern = timezone(timedelta(hours=-4))
    timestamp = datetime(2026, 10, 21, 14, 30, tzinfo=eastern)
    stored = PersonaService._db_timestamp(timestamp)
    assert stored == datetime(2026, 10, 21, 18, 30)
    assert stored.tzinfo is None


def test_persona_payload_uses_database_compatible_timestamps():
    persona = Persona(name="Troy", system_prompt="Design guidance.")
    payload = PersonaService._persona_payload(persona)
    assert payload["created_at"].tzinfo is None
    assert payload["updated_at"].tzinfo is None

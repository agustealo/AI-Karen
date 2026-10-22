"""Ensure existing persona edits and activation share a scoped transaction.

These structural guards complement the live PostgreSQL rollback tests required
before merge; they do not claim a database transaction was executed here.
"""
from pathlib import Path

SERVICE = Path("src/ai_karen_engine/services/persona/persona_service.py")
ROUTES = Path("src/ai_karen_engine/api_routes/users/persona.py")
UI = Path("src/ui_launchers/Karen-AI-Theme/src/components/settings/PersonaSettings.tsx")


def test_atomic_existing_persona_operation_has_one_transaction():
    source = SERVICE.read_text()
    start = source.index("    async def save_and_activate_existing_persona(")
    end = source.index("    async def delete_persona(", start)
    method = source[start:end]
    assert method.count("async with self._tenant_session(tenant_id) as session:") == 1
    assert "FOR UPDATE" in method
    assert "expected_revision" in method
    assert "UPDATE custom_personas SET" in method
    assert "UPDATE user_persona_preferences SET active_persona_id" in method
    assert "tenant_id = :tenant_id" in method
    assert "user_id = :user_id" in method
    assert method.index("UPDATE custom_personas SET") < method.index(
        "UPDATE user_persona_preferences SET active_persona_id"
    )


def test_route_and_editor_use_authoritative_operation():
    routes = ROUTES.read_text()
    editor = UI.read_text()
    assert '@router.post("/{persona_id}/save-and-activate"' in routes
    assert "await service.save_and_activate_existing_persona(" in routes
    assert "status_code=409" in routes
    assert "/save-and-activate" in editor
    assert "expected_revision: personaRevision" in editor

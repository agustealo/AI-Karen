from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/ai_karen_engine/app.py"
ROUTERS = ROOT / "server/routers.py"
LEGACY_MODEL_PREFERENCES = (
    ROOT / "src/ai_karen_engine/api_routes/users/preferences.py"
)


def test_canonical_app_quarantines_legacy_user_model_preferences() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "_prune_legacy_user_model_preferences" in source
    assert '"ai_karen_engine.api_routes.users.preferences"' in source
    assert "_prune_legacy_routes(app)" in source


def test_legacy_model_preference_router_is_marked_for_physical_removal() -> None:
    routers = ROUTERS.read_text(encoding="utf-8")
    legacy = LEGACY_MODEL_PREFERENCES.read_text(encoding="utf-8")

    # The compatibility import remains temporarily because server/routers.py is
    # concurrently edited by other backend work. The canonical app must quarantine
    # it until the import and file are removed together.
    assert "user_preferences_router" in routers
    assert 'default_model="llama3.2:latest"' in legacy
    assert '"status": "acknowledged"' in legacy


def test_legacy_model_preferences_are_not_a_valid_new_authority() -> None:
    legacy = LEGACY_MODEL_PREFERENCES.read_text(encoding="utf-8")

    assert "SettingsManager" in legacy
    assert "get_user_prefs" in legacy
    assert "could not be persisted" in legacy

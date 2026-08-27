from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/ai_karen_engine/app.py"
CANONICAL_ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
LEGACY_MODEL_PREFERENCES = (
    ROOT / "src/ai_karen_engine/api_routes/users/preferences.py"
)
ROOT_ROUTER_SHIM = ROOT / "server/routers.py"


def test_legacy_user_model_preferences_are_physically_removed() -> None:
    assert not LEGACY_MODEL_PREFERENCES.exists()


def test_canonical_router_registry_does_not_import_legacy_model_preferences() -> None:
    source = CANONICAL_ROUTERS.read_text(encoding="utf-8")

    assert "api_routes.users.preferences" not in source
    assert "user_preferences_router" not in source


def test_canonical_app_contains_no_preference_route_quarantine_after_deletion() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "_prune_legacy_user_model_preferences" not in source
    assert "_LEGACY_USER_MODEL_PREFERENCES_ENDPOINT_MODULE" not in source
    assert "_LEGACY_USER_MODEL_PREFERENCES_PRUNED_STATE_KEY" not in source


def test_root_router_is_only_a_canonical_compatibility_shim() -> None:
    source = ROOT_ROUTER_SHIM.read_text(encoding="utf-8")

    assert "from ai_karen_engine.server.routers import" in source
    assert "@app.middleware" not in source
    assert "app.include_router" not in source
    assert "tenant_id" not in source

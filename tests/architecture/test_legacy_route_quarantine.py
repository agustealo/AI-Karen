from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/ai_karen_engine/app.py"


def test_canonical_app_quarantines_legacy_user_model_preferences() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "_prune_legacy_user_model_preferences" in source
    assert '"ai_karen_engine.api_routes.users.preferences"' in source
    assert "_prune_legacy_routes(app)" in source


def test_legacy_user_model_preferences_cannot_bypass_canonical_route_pruning() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "_LEGACY_USER_MODEL_PREFERENCES_ENDPOINT_MODULE" in source
    assert "app.router.routes[:]" in source
    assert "_LEGACY_USER_MODEL_PREFERENCES_PRUNED_STATE_KEY" in source

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
APP = ROOT / "src/ai_karen_engine/app.py"

RETIRED_CONSUMER_SURFACES = (
    ROOT / "src/ai_karen_engine/api_routes/content/attachments.py",
    ROOT / "src/ai_karen_engine/services/tooling/file_attachment_service.py",
    ROOT / "src/ai_karen_engine/api_routes/users/data.py",
    ROOT / "src/ai_karen_engine/api_routes/models/management.py",
)


def test_unsafe_compatibility_and_legacy_surfaces_are_deleted() -> None:
    existing = [str(path.relative_to(ROOT)) for path in RETIRED_CONSUMER_SURFACES if path.exists()]
    assert not existing, f"retired consumer surfaces must stay deleted: {existing}"


def test_canonical_router_registry_does_not_remount_retired_surfaces() -> None:
    source = ROUTERS.read_text(encoding="utf-8")
    forbidden = (
        "api_routes.content.attachments",
        "api_routes.users.data",
        "api_routes.models.management",
        "file_attachment_router",
        "user_data_router",
        "model_management_router",
    )
    found = [token for token in forbidden if token in source]
    assert not found, f"retired routers must not be remounted: {found}"


def test_model_control_plane_is_admin_scoped_at_composition_boundary() -> None:
    source = ROUTERS.read_text(encoding="utf-8")
    assert "dependencies=(Depends(require_runtime_admin),)" in source
    assert (
        "app.dependency_overrides[model_orchestrator_current_user] = require_runtime_admin"
        in source
    )
    assert '{"admin", "super_admin"}' in source


def test_dead_legacy_model_pruning_is_removed() -> None:
    source = APP.read_text(encoding="utf-8")
    forbidden = (
        "_prune_legacy_provider_routes",
        "_prune_duplicate_legacy_model_routes",
        "_prune_removed_legacy_model_capabilities",
        "_prune_legacy_routes",
        "ai_karen_engine.api_routes.models.management",
    )
    found = [token for token in forbidden if token in source]
    assert not found, f"deleted legacy model authority left dead pruning code: {found}"

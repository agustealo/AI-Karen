from __future__ import annotations

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.services.admin.admin_training_control_service import (
    AdminTrainingControlService,
)


def test_training_control_plane_exposes_two_speed_adaptation(tmp_path):
    service = AdminTrainingControlService(
        registry=MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    )

    snapshot = service.snapshot()

    assert snapshot["architecture"]["strategy"] == "two_speed_adaptation"
    assert snapshot["architecture"]["weight_updates_are_immediate"] is False
    assert (
        snapshot["architecture"]["memory_is_training_data_source_not_model_weights"]
        is True
    )
    assert snapshot["registry"]["total_models"] == 0


def test_training_control_plane_includes_advanced_personalization_tasks(tmp_path):
    service = AdminTrainingControlService(
        registry=MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    )

    snapshot = service.snapshot()
    tasks = set(snapshot["prediction_tasks"])

    assert PredictionTask.AFFECT.value in tasks
    assert PredictionTask.PREFERENCE.value in tasks
    assert PredictionTask.OUTCOME_FORECAST.value in tasks
    assert PredictionTask.BEHAVIOR_PATTERN.value in tasks

    lanes = {lane["lane_id"]: lane for lane in snapshot["lanes"]}
    assert lanes["memory_adaptation"]["available"] is True
    assert lanes["reward_learning"]["available"] is True
    assert lanes["continual_learning"]["available"] is True
    assert lanes["proactive_forecasting"]["available"] is True


def test_training_control_plane_requires_shadow_governance(tmp_path):
    service = AdminTrainingControlService(
        registry=MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    )

    snapshot = service.snapshot()

    assert snapshot["governance"]["promotion_path"] == [
        "CANDIDATE",
        "SHADOW",
        "ACTIVE",
    ]
    controls = set(snapshot["governance"]["required_controls"])
    assert "tenant_isolation" in controls
    assert "sensitive_data_filtering" in controls
    assert "held_out_evaluation" in controls
    assert "shadow_evaluation" in controls


def test_admin_training_routes_are_mounted_by_canonical_router_registry():
    """The Admin UI must not receive 404 for a defined but unmounted endpoint."""
    from ai_karen_engine.api_routes.admin.training import router as training_router
    from ai_karen_engine.server.routers import CORE_ROUTERS

    mounts = [
        spec for spec in CORE_ROUTERS
        if spec.router is training_router and spec.prefix == "/api"
    ]
    assert len(mounts) == 1
    paths = {route.path for route in training_router.routes}
    assert "/admin/training/control-plane" in paths
    assert "/admin/training/advanced/catalog" in paths
    assert "/admin/training/advanced/jobs" in paths


def test_training_dataset_routes_are_mandatory_in_canonical_registry():
    from ai_karen_engine.api_routes.training.data import router as data_router
    from ai_karen_engine.server.routers import CORE_ROUTERS, OPTIONAL_ROUTERS

    assert sum(spec.router is data_router for spec in CORE_ROUTERS) == 1
    assert not any("api_routes.training.data" in module for module, *_ in OPTIONAL_ROUTERS)
    paths = {route.path for route in data_router.routes}
    assert "/api/training-data/datasets" in paths
    assert "/api/training-data/datasets/from-curated-memory" in paths

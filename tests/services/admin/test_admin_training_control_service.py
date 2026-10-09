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

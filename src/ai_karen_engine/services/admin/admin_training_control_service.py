"""Admin-facing intelligence training control-plane service.

This service is read-only. It composes backend truth from the canonical
intelligence, memory, learning, and model-registry authorities so the Admin
Training UI can show what Karen can learn, how adaptation is governed, and
where evidence is still insufficient. It deliberately does not execute model
training or mutate memory.
"""

from __future__ import annotations

from dataclasses import asdict
from importlib.util import find_spec
from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import ModelStatus, PredictionTask
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry


class AdminTrainingControlService:
    """Compose governed training/intelligence status without duplicating owners."""

    _LANES: tuple[dict[str, Any], ...] = (
        {
            "lane_id": "memory_adaptation",
            "title": "Memory adaptation",
            "category": "personalization",
            "authority": "core.memory",
            "module": "ai_karen_engine.core.memory.formation.service",
            "mode": "immediate_non_parametric",
            "description": (
                "Learns durable facts, preferences, episodes, lessons, and temporal "
                "state without changing model weights."
            ),
            "human_like_role": "episodic_semantic_memory",
        },
        {
            "lane_id": "profile_synthesis",
            "title": "User model synthesis",
            "category": "personalization",
            "authority": "core.memory.profile_synthesis",
            "module": "ai_karen_engine.core.memory.profile_synthesis.profile_manager",
            "mode": "evidence_synthesis",
            "description": (
                "Builds evolving user profiles from reinforced evidence while "
                "preserving contradiction and provenance handling."
            ),
            "human_like_role": "self_other_model",
        },
        {
            "lane_id": "procedural_learning",
            "title": "Procedural and lesson learning",
            "category": "memory",
            "authority": "core.memory.neuro",
            "module": "ai_karen_engine.core.memory.neuro.procedural_memory",
            "mode": "governed_memory",
            "description": (
                "Captures reusable lessons and successful procedures separately "
                "from personal facts."
            ),
            "human_like_role": "procedural_memory",
        },
        {
            "lane_id": "reward_learning",
            "title": "Outcome and reward learning",
            "category": "feedback",
            "authority": "core.intelligence.reward",
            "module": "ai_karen_engine.core.intelligence.reward",
            "mode": "evidence_weighted",
            "description": (
                "Projects completion, verification, durability, resilience, "
                "efficiency, and explicit feedback into quality evidence."
            ),
            "human_like_role": "reinforcement_signal",
        },
        {
            "lane_id": "online_learning",
            "title": "Online evidence calibration",
            "category": "ml",
            "authority": "core.intelligence.ml.online_learning",
            "module": "ai_karen_engine.core.intelligence.ml.online_learning",
            "mode": "threshold_adaptation",
            "description": (
                "Adapts confidence, latency, calibration, and fallback thresholds "
                "from observed model outcomes."
            ),
            "human_like_role": "metacognition",
        },
        {
            "lane_id": "continual_learning",
            "title": "Continual retraining",
            "category": "ml",
            "authority": "core.intelligence.ml.continual_learning",
            "module": "ai_karen_engine.core.intelligence.ml.continual_learning",
            "mode": "evidence_triggered",
            "description": (
                "Creates retraining candidates only after enough evidence reveals "
                "accuracy, calibration, or fallback regressions."
            ),
            "human_like_role": "slow_learning",
        },
        {
            "lane_id": "shadow_promotion",
            "title": "Shadow evaluation and promotion",
            "category": "governance",
            "authority": "core.intelligence.ml",
            "module": "ai_karen_engine.core.intelligence.ml.shadow",
            "mode": "candidate_shadow_active",
            "description": (
                "Keeps newly trained artifacts in candidate/shadow stages until "
                "measured improvement is demonstrated."
            ),
            "human_like_role": "reflection_before_habit",
        },
        {
            "lane_id": "proactive_forecasting",
            "title": "Next-need forecasting",
            "category": "forecasting",
            "authority": "core.intelligence.proactive",
            "module": "ai_karen_engine.core.intelligence.proactive.service",
            "mode": "evidence_ranked",
            "description": (
                "Ranks likely next needs from open loops, goals, prospective "
                "memory, and recurring behavior without authorizing execution."
            ),
            "human_like_role": "prospective_memory",
        },
        {
            "lane_id": "affect_learning",
            "title": "Affect and sentiment learning",
            "category": "affect",
            "authority": "core.intelligence.ml",
            "module": "ai_karen_engine.core.intelligence.ml.training.pipeline",
            "mode": "candidate_shadow_active",
            "prediction_task": PredictionTask.AFFECT.value,
            "description": (
                "Supports governed affect-state classification as evidence for "
                "response adaptation, never as a durable identity claim."
            ),
            "human_like_role": "social_affective_context",
        },
        {
            "lane_id": "preference_evolution",
            "title": "Preference evolution",
            "category": "personalization",
            "authority": "core.intelligence.ml",
            "module": "ai_karen_engine.core.intelligence.ml.training.pipeline",
            "mode": "candidate_shadow_active",
            "prediction_task": PredictionTask.PREFERENCE.value,
            "description": (
                "Learns probabilistic preference tendencies from repeated, "
                "validated behavior while memory remains the durable source of truth."
            ),
            "human_like_role": "adaptive_preference_model",
        },
        {
            "lane_id": "outcome_forecasting",
            "title": "Outcome forecasting",
            "category": "forecasting",
            "authority": "core.intelligence.ml",
            "module": "ai_karen_engine.core.intelligence.ml.training.pipeline",
            "mode": "candidate_shadow_active",
            "prediction_task": PredictionTask.OUTCOME_FORECAST.value,
            "description": (
                "Trains specialized predictors for likely task outcomes and risk; "
                "LLMs may explain forecasts but are not the numeric forecaster."
            ),
            "human_like_role": "anticipatory_reasoning",
        },
        {
            "lane_id": "behavior_pattern",
            "title": "Behavior-pattern learning",
            "category": "forecasting",
            "authority": "core.intelligence.ml",
            "module": "ai_karen_engine.core.intelligence.ml.training.pipeline",
            "mode": "candidate_shadow_active",
            "prediction_task": PredictionTask.BEHAVIOR_PATTERN.value,
            "description": (
                "Models recurring behavioral patterns from governed observations "
                "for continuity and anticipation."
            ),
            "human_like_role": "habit_learning",
        },
    )

    def __init__(self, registry: MLModelRegistry | None = None) -> None:
        self._registry = registry or MLModelRegistry()

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return find_spec(module_name) is not None
        except (ImportError, AttributeError, ValueError):
            return False

    def snapshot(self) -> dict[str, Any]:
        manifests = self._registry.list_all()
        models_by_task: dict[str, list[dict[str, Any]]] = {}
        status_counts = {status.value: 0 for status in ModelStatus}

        for manifest in manifests:
            status_counts[manifest.status] = status_counts.get(manifest.status, 0) + 1
            models_by_task.setdefault(manifest.purpose, []).append(
                {
                    "model_id": manifest.model_id,
                    "model_version": manifest.model_version,
                    "status": manifest.status,
                    "architecture": manifest.architecture,
                    "feature_version": manifest.feature_version,
                    "training_dataset_version": manifest.training_dataset_version,
                    "metrics": dict(manifest.metrics),
                    "created_at": manifest.created_at,
                }
            )

        lanes: list[dict[str, Any]] = []
        for lane in self._LANES:
            item = dict(lane)
            item["available"] = self._module_available(str(item["module"]))
            task = item.get("prediction_task")
            task_models = models_by_task.get(str(task), []) if task else []
            item["model_count"] = len(task_models)
            item["active_model_count"] = sum(
                1 for model in task_models if model["status"] == ModelStatus.ACTIVE.value
            )
            item["shadow_model_count"] = sum(
                1 for model in task_models if model["status"] == ModelStatus.SHADOW.value
            )
            item["candidate_model_count"] = sum(
                1 for model in task_models if model["status"] == ModelStatus.CANDIDATE.value
            )
            lanes.append(item)

        return {
            "architecture": {
                "strategy": "two_speed_adaptation",
                "fast_path": (
                    "Memory, temporal state, profile synthesis, reward evidence, and "
                    "calibration adapt without changing foundation-model weights."
                ),
                "slow_path": (
                    "Parametric models train from curated datasets, enter candidate "
                    "and shadow stages, and promote only after measured improvement."
                ),
                "weight_updates_are_immediate": False,
                "memory_is_training_data_source_not_model_weights": True,
                "llm_direct_forecasting": False,
            },
            "prediction_tasks": [task.value for task in PredictionTask],
            "lanes": lanes,
            "registry": {
                "total_models": len(manifests),
                "status_counts": status_counts,
                "models_by_task": models_by_task,
            },
            "governance": {
                "promotion_path": [
                    ModelStatus.CANDIDATE.value,
                    ModelStatus.SHADOW.value,
                    ModelStatus.ACTIVE.value,
                ],
                "required_controls": [
                    "tenant_isolation",
                    "rbac",
                    "provenance",
                    "sensitive_data_filtering",
                    "deletion_propagation",
                    "held_out_evaluation",
                    "calibration_check",
                    "regression_check",
                    "shadow_evaluation",
                    "audit_event",
                ],
                "personalization_rules": [
                    "Prefer memory/profile updates for immediate adaptation.",
                    "Treat affect as transient context unless repeated evidence supports a non-sensitive preference.",
                    "Do not convert inferred sensitive attributes into durable training labels.",
                    "Require repeated evidence before behavior or preference promotion.",
                    "Keep per-user adaptation scoped to that user unless explicitly approved for global learning.",
                ],
            },
        }


__all__ = ["AdminTrainingControlService"]

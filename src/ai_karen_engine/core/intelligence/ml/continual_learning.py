from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.online_learning import (
    AdaptiveLayer,
    EvidenceProfile,
    MLOutcomeCollector,
    MLEvidenceAggregator,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingArtifact,
    TrainingJob,
    TrainingJobStatus,
)
from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline, TrainingPipelineResult

logger = logging.getLogger(__name__)


@dataclass
class RetrainingTrigger:
    model_id: str
    model_version: str
    task: PredictionTask
    reason: str
    evidence_profile: EvidenceProfile
    metadata: dict[str, Any] = field(default_factory=dict)


class ContinualRetrainingPipeline:
    def __init__(
        self,
        registry: MLModelRegistry | None = None,
        training_pipeline: TrainingPipeline | None = None,
        adaptive_layer: AdaptiveLayer | None = None,
        collector: MLOutcomeCollector | None = None,
        aggregator: MLEvidenceAggregator | None = None,
    ) -> None:
        self._registry = registry or MLModelRegistry()
        self._training_pipeline = training_pipeline or TrainingPipeline(registry=self._registry)
        self._adaptive_layer = adaptive_layer or AdaptiveLayer(collector=collector, aggregator=aggregator)

    def evaluate_triggers(self, min_samples: int = 50) -> list[RetrainingTrigger]:
        triggers: list[RetrainingTrigger] = []
        profiles = self._adaptive_layer._aggregator.all_profiles()
        for key, profile in profiles.items():
            if profile.sample_count < min_samples:
                continue
            if profile.accuracy < 0.7:
                triggers.append(RetrainingTrigger(
                    model_id=profile.model_id,
                    model_version=profile.model_version,
                    task=profile.task,
                    reason="low_accuracy",
                    evidence_profile=profile,
                ))
            elif profile.avg_calibration_error > 0.1:
                triggers.append(RetrainingTrigger(
                    model_id=profile.model_id,
                    model_version=profile.model_version,
                    task=profile.task,
                    reason="poor_calibration",
                    evidence_profile=profile,
                ))
            elif profile.fallback_rate > 0.3:
                triggers.append(RetrainingTrigger(
                    model_id=profile.model_id,
                    model_version=profile.model_version,
                    task=profile.task,
                    reason="high_fallback_rate",
                    evidence_profile=profile,
                ))
        return triggers

    def submit_retraining_job(self, trigger: RetrainingTrigger, base_model: str = "base") -> TrainingPipelineResult:
        active = self._registry.get_active(trigger.task.value)
        base = active.model_id if active else base_model
        job = TrainingJob(
            job_id=f"retrain-{trigger.model_id}-{trigger.task.value}",
            task=trigger.task.value,
            base_model=base,
            dataset_version="ml-eval-v1",
            training_config_version="continual-v1",
            status=TrainingJobStatus.QUEUED.value,
            metadata={"trigger_reason": trigger.reason, "trigger_model_id": trigger.model_id},
        )
        result = self._training_pipeline.submit(job)
        logger.info("Submitted retraining job %s for model %s due to %s", job.job_id, trigger.model_id, trigger.reason)
        return result

    async def run_retraining(self, result: TrainingPipelineResult) -> TrainingPipelineResult:
        return await self._training_pipeline.run(result)

    def get_evidence_profile(self, model_id: str, model_version: str, task: PredictionTask) -> EvidenceProfile | None:
        return self._adaptive_layer.get_profile(model_id, model_version, task)

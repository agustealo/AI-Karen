from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TrainingJobStatus(str, Enum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TrainingJob:
    job_id: str
    task: str
    base_model: str
    dataset_version: str
    training_config_version: str = ""
    seed: int = 42
    started_at: str = ""
    completed_at: str = ""
    status: str = TrainingJobStatus.QUEUED.value
    artifact_path: str = ""
    artifact_hash: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    resource_usage: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingArtifact:
    artifact_path: str
    artifact_hash: str
    model_id: str
    model_version: str
    task: str
    dataset_version: str
    training_config_version: str
    metrics: dict[str, Any] = field(default_factory=dict)
    resource_usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingPipelineResult:
    job: TrainingJob
    artifact: TrainingArtifact | None = None
    registered: bool = False
    evaluation_result: Any = None
    error: str | None = None

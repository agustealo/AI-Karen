from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class LearningTask(str, Enum):
    """Neutral supervised-learning task identifiers.

    Phase 2 (runtime) produces examples; Phase 1 (intelligence/ml) consumes
    them. The enum is intentionally shared and phase-independent so neither
    side imports the other's implementation.
    """

    EXECUTION_TOPOLOGY = "execution_topology"
    PROVIDER_SELECTION = "provider_selection"
    MODEL_SELECTION = "model_selection"
    AGENT_SELECTION = "agent_selection"
    TOOL_SELECTION = "tool_selection"
    PLUGIN_SELECTION = "plugin_selection"
    MEMORY_SELECTION = "memory_selection"


class LabelQuality(str, Enum):
    """Quality of a training label with respect to runtime truth.

    HIGH    - execution success, policy valid, no infrastructure failure
    MEDIUM  - partial success or recoverable fallback
    LOW     - outcome unavailable or weakly verified
    EXCLUDED - record must not train a model (see exclusion reasons)
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    EXCLUDED = "excluded"


class DatasetExclusionReason(str, Enum):
    """Why a record was excluded from a training dataset."""

    MISSING_FEATURE_SNAPSHOT = "missing_feature_snapshot"
    MISSING_DECISION_OBSERVATION = "missing_decision_observation"
    MISSING_OUTCOME = "missing_outcome"
    UNKNOWN_FEATURE_VERSION = "unknown_feature_version"
    INVALID_TOPOLOGY_LABEL = "invalid_topology_label"
    LABEL_QUALITY_BELOW_MINIMUM = "label_quality_below_minimum"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    SECURITY_DENIAL = "security_denial"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROVIDER_OUTAGE = "provider_outage"
    DATABASE_OUTAGE = "database_outage"
    CORRUPT_CONFIG = "corrupt_config"
    CANCELLED_BEFORE_EXECUTION = "cancelled_before_execution"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class LearningExample:
    """Neutral, phase-independent supervised training example.

    Produced by Phase 2 (runtime) and consumed by Phase 1 (intelligence/ml).
    It MUST NOT import any runtime or ML implementation so the dependency
    direction stays ML -> neutral contracts (or both consume neutral).

    ``features`` is the model feature vector. ``metadata`` holds provenance
    (trajectory/observation/tenant ids) and MUST NOT leak into ``features``:
    user/tenant identifiers are audit metadata, never model inputs.
    """

    example_id: str
    task: LearningTask
    feature_version: str
    features: dict[str, Any]
    label: Any
    label_quality: LabelQuality = LabelQuality.HIGH
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "example_id": self.example_id,
            "task": self.task.value,
            "feature_version": self.feature_version,
            "features": self.features,
            "label": self.label,
            "label_quality": self.label_quality.value,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningExample:
        return cls(
            example_id=data["example_id"],
            task=LearningTask(data["task"]),
            feature_version=data["feature_version"],
            features=data.get("features", {}),
            label=data.get("label"),
            label_quality=LabelQuality(data.get("label_quality", "high")),
            metadata=data.get("metadata", {}),
        )


@dataclass(slots=True)
class LearningDatasetQuery:
    """Neutral query describing which records compose a dataset.

    No hardcoded "last 7 days" lives in builder logic; the caller supplies the
    window and quality floor so retraining and drift analysis stay flexible.
    """

    task: LearningTask
    start_time: datetime | None = None
    end_time: datetime | None = None
    minimum_label_quality: LabelQuality = LabelQuality.LOW
    feature_version: str | None = None
    tenant_scope: str | None = None


@dataclass(slots=True)
class LearningDatasetManifest:
    """Immutable provenance for a built training dataset.

    Answers: what exact runtime evidence trained model X?
    """

    dataset_id: str
    dataset_version: str
    task: LearningTask
    feature_version: str
    source_time_range: tuple[datetime | None, datetime | None]
    record_count: int
    included_count: int
    excluded_count: int
    builder_version: str
    schema_version: str
    created_at: datetime
    source_trajectory_ids: list[str] = field(default_factory=list)
    source_decision_observation_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "task": self.task.value,
            "feature_version": self.feature_version,
            "source_time_range": [
                t.isoformat() if t else None for t in self.source_time_range
            ],
            "record_count": self.record_count,
            "included_count": self.included_count,
            "excluded_count": self.excluded_count,
            "builder_version": self.builder_version,
            "schema_version": self.schema_version,
            "created_at": self.created_at.isoformat(),
            "source_trajectory_ids": self.source_trajectory_ids,
            "source_decision_observation_ids": self.source_decision_observation_ids,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningDatasetManifest:
        range_raw = data.get("source_time_range", [None, None])
        time_range = (
            datetime.fromisoformat(range_raw[0]) if range_raw[0] else None,
            datetime.fromisoformat(range_raw[1]) if range_raw[1] else None,
        )
        return cls(
            dataset_id=data["dataset_id"],
            dataset_version=data["dataset_version"],
            task=LearningTask(data["task"]),
            feature_version=data["feature_version"],
            source_time_range=time_range,
            record_count=data["record_count"],
            included_count=data["included_count"],
            excluded_count=data["excluded_count"],
            builder_version=data["builder_version"],
            schema_version=data["schema_version"],
            created_at=datetime.fromisoformat(data["created_at"]),
            source_trajectory_ids=data.get("source_trajectory_ids", []),
            source_decision_observation_ids=data.get(
                "source_decision_observation_ids", []
            ),
            metadata=data.get("metadata", {}),
        )


@dataclass(slots=True)
class ExcludedRecord:
    """A record that was considered but excluded from a dataset, with reason."""

    trajectory_id: str
    decision_observation_id: str | None
    feature_snapshot_id: str | None
    reason: DatasetExclusionReason
    label_quality: LabelQuality = LabelQuality.EXCLUDED
    detail: str | None = None


SCHEMA_VERSION = "1.0"

BUILDER_VERSION = "phase2-1.0"

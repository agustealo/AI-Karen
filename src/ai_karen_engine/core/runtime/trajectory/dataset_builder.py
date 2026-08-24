from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_karen_engine.core.contracts.learning import (
    BUILDER_VERSION,
    SCHEMA_VERSION,
    DatasetExclusionReason,
    ExcludedRecord,
    LabelQuality,
    LearningDatasetManifest,
    LearningDatasetQuery,
    LearningExample,
    LearningTask,
)
from ai_karen_engine.core.observability import RuntimeEventType
from ai_karen_engine.core.observability import emit as _emit_event
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionObservation,
    DecisionType,
)

# Decision observations of these types feed the matching LearningTask.
_DECISION_TYPE_TO_TASK = {
    DecisionType.EXECUTION_TOPOLOGY.value: LearningTask.EXECUTION_TOPOLOGY,
    DecisionType.PROVIDER_SELECTION.value: LearningTask.PROVIDER_SELECTION,
    DecisionType.MODEL_SELECTION.value: LearningTask.MODEL_SELECTION,
    DecisionType.AGENT_SELECTION.value: LearningTask.AGENT_SELECTION,
    DecisionType.TOOL_SELECTION.value: LearningTask.TOOL_SELECTION,
    DecisionType.PLUGIN_SELECTION.value: LearningTask.PLUGIN_SELECTION,
    DecisionType.MEMORY_SELECTION.value: LearningTask.MEMORY_SELECTION,
}

# Execution failures that do NOT imply the chosen topology was wrong.
_INFRASTRUCTURE_ERROR_CODES = {
    "AUTHENTICATION_FAILURE",
    "SECURITY_DENIAL",
    "DATABASE_OUTAGE",
    "PROVIDER_OUTAGE",
    "CORRUPT_CONFIG",
    "CANCELLED",
    "CANCELLED_BEFORE_EXECUTION",
}

_QUALITY_RANK = {
    LabelQuality.EXCLUDED: 0,
    LabelQuality.LOW: 1,
    LabelQuality.MEDIUM: 2,
    LabelQuality.HIGH: 3,
}


@dataclass
class LearningDatasetResult:
    """Outcome of a dataset build: manifest, examples, excluded records, paths."""

    manifest: LearningDatasetManifest
    examples: list[LearningExample] = field(default_factory=list)
    excluded: list[ExcludedRecord] = field(default_factory=list)
    data_path: str | None = None
    manifest_path: str | None = None


class LearningDatasetStore:
    """Writes built datasets as durable, immutable artifacts.

    Defaults to JSONL + a sidecar manifest. Parquet is used only when
    explicitly configured and pyarrow is importable; we never invent a new
    feature-store service.
    """

    def __init__(self, *, dataset_dir: str, dataset_format: str = "jsonl") -> None:
        self._dataset_dir = dataset_dir
        self._format = dataset_format

    def _paths(self, task: LearningTask, dataset_version: str) -> tuple[Path, Path]:
        base = Path(self._dataset_dir) / task.value
        base.mkdir(parents=True, exist_ok=True)
        return (
            base / f"{dataset_version}.jsonl",
            base / f"{dataset_version}.manifest.json",
        )

    def save_dataset(
        self,
        manifest: LearningDatasetManifest,
        examples: list[LearningExample],
    ) -> tuple[str, str]:
        data_path, manifest_path = self._paths(manifest.task, manifest.dataset_version)

        if self._format == "parquet":
            try:
                self._write_parquet(data_path, examples)
            except Exception:  # noqa: BLE001
                data_path = data_path.with_suffix(".jsonl")
                self._write_jsonl(data_path, examples)
        else:
            self._write_jsonl(data_path, examples)

        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        return str(data_path), str(manifest_path)

    @staticmethod
    def _write_jsonl(path: Path, examples: list[LearningExample]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for example in examples:
                handle.write(json.dumps(example.to_dict(), default=str) + "\n")

    @staticmethod
    def _write_parquet(path: Path, examples: list[LearningExample]) -> None:
        import pyarrow.json as pyarrow_json  # type: ignore

        rows = [example.to_dict() for example in examples]
        pyarrow_json.write_json(str(path), json.dumps(rows))

    def read_examples(
        self, task: LearningTask, dataset_version: str
    ) -> list[LearningExample]:
        data_path, _ = self._paths(task, dataset_version)
        examples: list[LearningExample] = []
        if not data_path.exists():
            return examples
        with data_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                examples.append(LearningExample.from_dict(json.loads(line)))
        return examples

    def read_manifest(
        self, task: LearningTask, dataset_version: str
    ) -> LearningDatasetManifest | None:
        _, manifest_path = self._paths(task, dataset_version)
        if not manifest_path.exists():
            return None
        return LearningDatasetManifest.from_dict(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )


class LearningDatasetBuilder:
    """Assembles versioned, reproducible supervised training datasets.

    Consumes only runtime truth contracts (trajectories, snapshots,
    observations, outcomes). It does NOT import any intelligence/ml or
    adaptive implementation, so the runtime stays the witness, not the
    learner. Phase 1 adapts the neutral ``LearningExample`` contract.
    """

    def __init__(
        self,
        trajectory_store: Any,
        outcome_store: Any,
        *,
        settings: Any | None = None,
        dataset_store: LearningDatasetStore | None = None,
    ) -> None:
        self._trajectory_store = trajectory_store
        self._outcome_store = outcome_store
        self._settings = settings
        self._dataset_store = dataset_store

    def build(self, query: LearningDatasetQuery) -> LearningDatasetResult:
        if query.tenant_scope is None:
            raise ValueError(
                "dataset building requires an explicit tenant_scope; cross-tenant "
                "aggregation uses a separate governed path"
            )

        _emit_event(
            RuntimeEventType.LEARNING_DATASET_BUILD_STARTED,
            tenant_scope=query.tenant_scope,
            metadata={
                "task": query.task.value,
                "feature_version": query.feature_version,
                "minimum_label_quality": query.minimum_label_quality.value,
                "start_time": query.start_time.isoformat() if query.start_time else None,
                "end_time": query.end_time.isoformat() if query.end_time else None,
            },
        )

        try:
            examples: list[LearningExample] = []
            excluded: list[ExcludedRecord] = []
            source_trajectory_ids: set[str] = set()
            source_observation_ids: set[str] = set()

            trajectories = self._trajectory_store.list_for_tenant(
                query.tenant_scope, limit=100_000
            )
            for trajectory in trajectories:
                if not self._in_time_window(trajectory, query):
                    continue
                observations = self._trajectory_store.list_decision_observations(
                    trajectory.trajectory_id
                )
                outcomes = self._outcome_store.get_for_trajectory(
                    trajectory.trajectory_id
                )
                for observation in observations:
                    if _DECISION_TYPE_TO_TASK.get(observation.decision_type) != query.task:
                        continue
                    source_trajectory_ids.add(trajectory.trajectory_id)
                    source_observation_ids.add(observation.decision_observation_id)

                    example, exclusion = self._try_build_example(
                        trajectory, observation, outcomes, query
                    )
                    if example is not None:
                        examples.append(example)
                    if exclusion is not None:
                        excluded.append(exclusion)

            manifest = self._build_manifest(
                query, examples, excluded, source_trajectory_ids, source_observation_ids
            )

            data_path = None
            manifest_path = None
            if self._dataset_store is not None:
                data_path, manifest_path = self._dataset_store.save_dataset(
                    manifest, examples
                )

            _emit_event(
                RuntimeEventType.LEARNING_DATASET_BUILD_COMPLETED,
                status="success",
                tenant_scope=query.tenant_scope,
                metadata={
                    "dataset_version": manifest.dataset_version,
                    "included_count": manifest.included_count,
                    "excluded_count": manifest.excluded_count,
                    "record_count": manifest.record_count,
                },
            )
            return LearningDatasetResult(
                manifest=manifest,
                examples=examples,
                excluded=excluded,
                data_path=data_path,
                manifest_path=manifest_path,
            )
        except Exception as exc:
            _emit_event(
                RuntimeEventType.LEARNING_DATASET_BUILD_FAILED,
                status="failed",
                error_type=type(exc).__name__,
                tenant_scope=query.tenant_scope,
                metadata={"task": query.task.value, "error": str(exc)},
            )
            raise

    @staticmethod
    def _in_time_window(trajectory: Any, query: LearningDatasetQuery) -> bool:
        started = getattr(trajectory, "started_at", None)
        if started is None:
            return True
        return not (
            (query.start_time is not None and started < query.start_time)
            or (query.end_time is not None and started > query.end_time)
        )

    def _try_build_example(
        self,
        trajectory: Any,
        observation: DecisionObservation,
        outcomes: list[dict[str, Any]],
        query: LearningDatasetQuery,
    ) -> tuple[LearningExample | None, ExcludedRecord | None]:
        snapshot = self._trajectory_store.get_feature_snapshot(
            observation.feature_snapshot_id
        )
        if snapshot is None:
            return None, ExcludedRecord(
                trajectory_id=trajectory.trajectory_id,
                decision_observation_id=observation.decision_observation_id,
                feature_snapshot_id=observation.feature_snapshot_id,
                reason=DatasetExclusionReason.MISSING_FEATURE_SNAPSHOT,
            )

        if (
            query.feature_version is not None
            and snapshot.feature_version != query.feature_version
        ):
            return None, ExcludedRecord(
                trajectory_id=trajectory.trajectory_id,
                decision_observation_id=observation.decision_observation_id,
                feature_snapshot_id=observation.feature_snapshot_id,
                reason=DatasetExclusionReason.UNKNOWN_FEATURE_VERSION,
                detail=f"expected {query.feature_version}, got {snapshot.feature_version}",
            )

        label = self._resolve_topology_label(trajectory, observation)
        if label is None:
            return None, ExcludedRecord(
                trajectory_id=trajectory.trajectory_id,
                decision_observation_id=observation.decision_observation_id,
                feature_snapshot_id=observation.feature_snapshot_id,
                reason=DatasetExclusionReason.INVALID_TOPOLOGY_LABEL,
            )

        quality, infra_reason = self._assess_label_quality(trajectory, outcomes)

        if infra_reason is not None:
            return None, ExcludedRecord(
                trajectory_id=trajectory.trajectory_id,
                decision_observation_id=observation.decision_observation_id,
                feature_snapshot_id=observation.feature_snapshot_id,
                reason=infra_reason,
                label_quality=LabelQuality.EXCLUDED,
            )

        if _QUALITY_RANK[quality] < _QUALITY_RANK[query.minimum_label_quality]:
            return None, ExcludedRecord(
                trajectory_id=trajectory.trajectory_id,
                decision_observation_id=observation.decision_observation_id,
                feature_snapshot_id=observation.feature_snapshot_id,
                reason=DatasetExclusionReason.LABEL_QUALITY_BELOW_MINIMUM,
                label_quality=quality,
            )

        latest_outcome = self._latest_execution_outcome(outcomes)
        example = LearningExample(
            example_id=f"ex_{uuid.uuid4().hex}",
            task=query.task,
            feature_version=snapshot.feature_version,
            features=snapshot.feature_vector(),
            label=label,
            label_quality=quality,
            metadata={
                "trajectory_id": trajectory.trajectory_id,
                "decision_observation_id": observation.decision_observation_id,
                "feature_snapshot_id": observation.feature_snapshot_id,
                "outcome_id": latest_outcome.get("outcome_id")
                if latest_outcome is not None
                else None,
                "tenant_id": observation.tenant_id,
                "user_id": observation.user_id,
                "decision_type": observation.decision_type,
                "behavior_policy_id": observation.behavior_policy_id,
                "behavior_policy_version": observation.behavior_policy_version,
                "ope_eligible": observation.ope_eligible,
                "created_at": observation.created_at.isoformat(),
            },
        )
        return example, None

    @staticmethod
    def _resolve_topology_label(
        trajectory: Any, observation: DecisionObservation
    ) -> str | None:
        executed = getattr(trajectory, "executed_topology", None)
        if executed:
            return executed
        cortex = getattr(trajectory, "cortex_decision", None)
        if isinstance(cortex, dict) and cortex.get("topology"):
            return str(cortex["topology"])
        if observation.chosen_action:
            return observation.chosen_action
        return None

    @staticmethod
    def _latest_execution_outcome(
        outcomes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        execution_outcomes = [o for o in outcomes if "status" in o]
        if not execution_outcomes:
            return None
        return execution_outcomes[-1]

    @classmethod
    def _assess_label_quality(
        cls, trajectory: Any, outcomes: list[dict[str, Any]]
    ) -> tuple[LabelQuality, DatasetExclusionReason | None]:
        outcome = cls._latest_execution_outcome(outcomes)
        error_code = getattr(trajectory, "error_code", None)
        status = None
        if outcome is not None:
            status = outcome.get("status")

        if status is None and error_code is None:
            return LabelQuality.LOW, None

        if error_code in _INFRASTRUCTURE_ERROR_CODES:
            return LabelQuality.EXCLUDED, cls._map_infra_reason(error_code)
        if status == "cancelled":
            return LabelQuality.EXCLUDED, DatasetExclusionReason.CANCELLED_BEFORE_EXECUTION

        if status == "success":
            completed = outcome.get("response_completed") if outcome is not None else None
            if completed is False:
                return LabelQuality.MEDIUM, None
            return LabelQuality.HIGH, None
        if status == "partial_success":
            return LabelQuality.MEDIUM, None
        if status == "failure":
            return LabelQuality.LOW, None
        return LabelQuality.LOW, None

    @staticmethod
    def _map_infra_reason(error_code: str) -> DatasetExclusionReason:
        # Auth/security/denial keep their specific reasons; infrastructure
        # outages collapse to INFRASTRUCTURE_FAILURE so the poisoning scenario
        # is excluded without implying the chosen topology was wrong.
        mapping = {
            "AUTHENTICATION_FAILURE": DatasetExclusionReason.AUTHENTICATION_FAILURE,
            "SECURITY_DENIAL": DatasetExclusionReason.SECURITY_DENIAL,
            "CORRUPT_CONFIG": DatasetExclusionReason.CORRUPT_CONFIG,
            "DATABASE_OUTAGE": DatasetExclusionReason.INFRASTRUCTURE_FAILURE,
            "PROVIDER_OUTAGE": DatasetExclusionReason.INFRASTRUCTURE_FAILURE,
            "CANCELLED": DatasetExclusionReason.CANCELLED_BEFORE_EXECUTION,
            "CANCELLED_BEFORE_EXECUTION": DatasetExclusionReason.CANCELLED_BEFORE_EXECUTION,
        }
        return mapping.get(error_code, DatasetExclusionReason.INFRASTRUCTURE_FAILURE)

    def _build_manifest(
        self,
        query: LearningDatasetQuery,
        examples: list[LearningExample],
        excluded: list[ExcludedRecord],
        source_trajectory_ids: set[str],
        source_observation_ids: set[str],
    ) -> LearningDatasetManifest:
        created_at = datetime.utcnow()
        dataset_version = f"{query.task.value}-{created_at:%Y%m%dT%H%M%SZ}-v1"
        return LearningDatasetManifest(
            dataset_id=f"ds_{uuid.uuid4().hex}",
            dataset_version=dataset_version,
            task=query.task,
            feature_version=query.feature_version or "",
            source_time_range=(query.start_time, query.end_time),
            record_count=len(examples) + len(excluded),
            included_count=len(examples),
            excluded_count=len(excluded),
            builder_version=BUILDER_VERSION,
            schema_version=SCHEMA_VERSION,
            created_at=created_at,
            source_trajectory_ids=sorted(source_trajectory_ids),
            source_decision_observation_ids=sorted(source_observation_ids),
        )


def build_dataset_builder(
    trajectory_store: Any,
    outcome_store: Any,
    *,
    settings: Any | None = None,
) -> LearningDatasetBuilder:
    """Create a ``LearningDatasetBuilder`` wired to canonical learning config.

    If learning recording is disabled, the builder still runs but writes no
    dataset files (dataset_store left None) so callers can preview provenance.
    """
    if settings is None:
        from ai_karen_engine.config.learning import get_learning_settings

        settings = get_learning_settings()

    dataset_store: LearningDatasetStore | None = None
    if getattr(settings, "recording_enabled", True):
        dataset_store = LearningDatasetStore(
            dataset_dir=settings.dataset_dir,
            dataset_format=settings.dataset_format,
        )
    return LearningDatasetBuilder(
        trajectory_store, outcome_store, settings=settings, dataset_store=dataset_store
    )

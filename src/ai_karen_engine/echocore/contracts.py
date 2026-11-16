from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    STM = "stm"
    EPISODIC = "episodic"
    LTM = "ltm"


class EchoArtifactType(str, Enum):
    EPISODIC_EVENT = "episodic_event"
    LONG_TERM_FACT = "long_term_fact"
    USER_PREFERENCE = "user_preference"
    PROJECT_MEMORY = "project_memory"
    TRAINING_CANDIDATE = "training_candidate"
    ARCHIVAL_RECORD = "archival_record"
    SHADOW_SIGNAL = "shadow_signal"
    METADATA_SIGNAL = "metadata_signal"


class EchoIngestAction(str, Enum):
    ARCHIVE = "archive"
    ENRICH_METADATA = "enrich_metadata"
    QUEUE_TRAINING = "queue_training"
    STORE_SHADOW = "store_shadow"
    DROP = "drop"


@dataclass(slots=True)
class RuntimeMemoryArtifact:
    artifact_id: str
    artifact_type: EchoArtifactType
    source_tier: MemoryTier
    user_id: str
    tenant_id: Optional[str]
    session_id: Optional[str]
    thread_id: Optional[str]
    content: Dict[str, Any]
    importance_score: float = 0.0
    retention_score: float = 0.0
    privacy_tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Carries the upstream source veto across the memory/EchoCore boundary.
    # This is advisory for rejection only; "eligible" never authorizes training.
    training_eligibility: str = "review"


@dataclass(slots=True)
class EchoPolicyDecision:
    action: EchoIngestAction
    should_archive: bool = False
    should_collect_metadata: bool = True
    should_queue_training: bool = False
    should_store_shadow: bool = False
    should_create_backup_copy: bool = False
    reason: str = ""


@dataclass(slots=True)
class EchoArchiveRecord:
    record_id: str
    artifact_id: str
    user_id: str
    tenant_id: Optional[str]
    record_type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EchoMetadataRecord:
    artifact_id: str
    user_id: str
    tenant_id: Optional[str]
    signals: Dict[str, Any]
    tags: List[str] = field(default_factory=list)


@dataclass(slots=True)
class EchoTrainingCandidate:
    artifact_id: str
    user_id: str
    tenant_id: Optional[str]
    input_payload: Dict[str, Any]
    labels: Dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0


@dataclass(slots=True)
class EchoShadowRecord:
    artifact_id: str
    user_id: str
    tenant_id: Optional[str]
    shadow_signals: Dict[str, Any]
    restricted: bool = True


@dataclass(slots=True)
class EchoIngestResult:
    artifact_id: str
    decision: EchoPolicyDecision
    archive_record_id: Optional[str] = None
    metadata_written: bool = False
    training_queued: bool = False
    shadow_written: bool = False
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class EchoVault(Protocol):
    async def store_archive(self, record: EchoArchiveRecord) -> str:
        ...

    async def store_backup_copy(self, record: EchoArchiveRecord) -> str:
        ...


class MetadataCollector(Protocol):
    def collect(self, artifact: RuntimeMemoryArtifact) -> EchoMetadataRecord:
        ...


class FineTuner(Protocol):
    def queue_candidate(self, candidate: EchoTrainingCandidate) -> None:
        ...


class DarkTracker(Protocol):
    async def store_shadow(self, record: EchoShadowRecord) -> None:
        ...


class TelemetryManager(Protocol):
    def emit_ingest(self, result: EchoIngestResult) -> None:
        ...


class EchoPolicyEngine:
    def evaluate(self, artifact: RuntimeMemoryArtifact) -> EchoPolicyDecision:
        if artifact.artifact_type in {
            EchoArtifactType.LONG_TERM_FACT,
            EchoArtifactType.USER_PREFERENCE,
            EchoArtifactType.PROJECT_MEMORY,
        }:
            return EchoPolicyDecision(
                action=EchoIngestAction.ARCHIVE,
                should_archive=True,
                should_collect_metadata=True,
                should_queue_training=False,
                should_create_backup_copy=True,
                reason="durable high-value memory",
            )

        if artifact.artifact_type == EchoArtifactType.EPISODIC_EVENT:
            return EchoPolicyDecision(
                action=EchoIngestAction.ENRICH_METADATA,
                should_archive=artifact.retention_score >= 0.80,
                should_collect_metadata=True,
                should_queue_training=False,
                reason="episodic event evaluation",
            )

        if artifact.artifact_type == EchoArtifactType.SHADOW_SIGNAL:
            return EchoPolicyDecision(
                action=EchoIngestAction.STORE_SHADOW,
                should_collect_metadata=True,
                should_store_shadow=True,
                reason="restricted shadow signal",
            )

        return EchoPolicyDecision(
            action=EchoIngestAction.DROP,
            should_collect_metadata=False,
            reason="low-value artifact",
        )


class DefaultEchoCoreManager:
    def __init__(
        self,
        policy_engine: EchoPolicyEngine,
        echo_vault: EchoVault,
        metadata_collector: MetadataCollector,
        fine_tuner: FineTuner,
        dark_tracker: DarkTracker,
        telemetry_manager: TelemetryManager,
    ) -> None:
        self._policy_engine = policy_engine
        self._echo_vault = echo_vault
        self._metadata_collector = metadata_collector
        self._fine_tuner = fine_tuner
        self._dark_tracker = dark_tracker
        self._telemetry_manager = telemetry_manager

    async def ingest(self, artifact: RuntimeMemoryArtifact) -> EchoIngestResult:
        decision = self._policy_engine.evaluate(artifact)
        result = EchoIngestResult(
            artifact_id=artifact.artifact_id,
            decision=decision,
        )

        metadata_record: Optional[EchoMetadataRecord] = None
        if decision.should_collect_metadata:
            try:
                metadata_record = self._metadata_collector.collect(artifact)
                result.metadata_written = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Echo metadata collection failed for %s: %s", artifact.artifact_id, exc)
                result.diagnostics["metadata_error"] = str(exc)

        if decision.should_archive:
            archive_record = EchoArchiveRecord(
                record_id=f"echo-{artifact.artifact_id}",
                artifact_id=artifact.artifact_id,
                user_id=artifact.user_id,
                tenant_id=artifact.tenant_id,
                record_type=artifact.artifact_type.value,
                payload=artifact.content,
                metadata=(metadata_record.signals if metadata_record else {}),
            )
            try:
                record_id = await self._echo_vault.store_archive(archive_record)
                result.archive_record_id = record_id
                if decision.should_create_backup_copy:
                    await self._echo_vault.store_backup_copy(archive_record)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Echo archive write failed for %s: %s", artifact.artifact_id, exc)
                result.diagnostics["archive_error"] = str(exc)

        # Training is a separate governed admission workflow. Memory worthiness,
        # importance and legacy policy engines cannot authorize model updates.
        if decision.should_queue_training:
            result.diagnostics["training_request_blocked"] = (
                "independent_admission_required"
            )

        if decision.should_store_shadow:
            shadow_record = EchoShadowRecord(
                artifact_id=artifact.artifact_id,
                user_id=artifact.user_id,
                tenant_id=artifact.tenant_id,
                shadow_signals=artifact.content,
            )
            try:
                await self._dark_tracker.store_shadow(shadow_record)
                result.shadow_written = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Echo shadow store failed for %s: %s", artifact.artifact_id, exc)
                result.diagnostics["shadow_error"] = str(exc)

        result.diagnostics = {
            **result.diagnostics,
            "artifact_type": artifact.artifact_type.value,
            "source_tier": artifact.source_tier.value,
            "decision_action": decision.action.value,
        }

        try:
            self._telemetry_manager.emit_ingest(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Echo telemetry emit failed for %s: %s", artifact.artifact_id, exc)
            result.diagnostics["telemetry_error"] = str(exc)

        return result


__all__ = [
    "MemoryTier",
    "EchoArtifactType",
    "EchoIngestAction",
    "RuntimeMemoryArtifact",
    "EchoPolicyDecision",
    "EchoArchiveRecord",
    "EchoMetadataRecord",
    "EchoTrainingCandidate",
    "EchoShadowRecord",
    "EchoIngestResult",
    "EchoVault",
    "MetadataCollector",
    "FineTuner",
    "DarkTracker",
    "TelemetryManager",
    "EchoPolicyEngine",
    "DefaultEchoCoreManager",
]

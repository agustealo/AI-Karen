from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol

from ai_karen_engine.echocore.contracts import (
    DefaultEchoCoreManager,
    EchoArtifactType,
    MemoryTier,
    RuntimeMemoryArtifact,
)

logger = logging.getLogger(__name__)


class RuntimeToEchoBridge(Protocol):
    def export_artifacts(self, write_result: Dict[str, Any]) -> List[RuntimeMemoryArtifact]:
        ...


class DefaultRuntimeToEchoBridge:
    def export_artifacts(self, write_result: Dict[str, Any]) -> List[RuntimeMemoryArtifact]:
        artifacts: List[RuntimeMemoryArtifact] = []

        for item in self._items_from_result(write_result, "promoted_ltm_records", "ltm_records", "promoted_records"):
            artifacts.append(self._build_artifact(item, MemoryTier.LTM))

        for item in self._items_from_result(write_result, "episodic_records", "episodic", "event_records"):
            artifacts.append(self._build_artifact(item, MemoryTier.EPISODIC))

        for item in self._items_from_result(write_result, "shadow_records", "shadow_artifacts"):
            artifacts.append(self._build_artifact(item, MemoryTier.STM))

        return artifacts

    async def ingest_write_result(
        self,
        write_result: Dict[str, Any],
        manager: DefaultEchoCoreManager,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for artifact in self.export_artifacts(write_result):
            ingest_result = await manager.ingest(artifact)
            results.append(
                {
                    "artifact_id": ingest_result.artifact_id,
                    "decision": ingest_result.decision.action.value,
                    "archive_record_id": ingest_result.archive_record_id,
                    "metadata_written": ingest_result.metadata_written,
                    "training_queued": ingest_result.training_queued,
                    "shadow_written": ingest_result.shadow_written,
                    "diagnostics": ingest_result.diagnostics,
                }
            )
        return results

    def _build_artifact(
        self,
        item: Dict[str, Any],
        source_tier: MemoryTier,
    ) -> RuntimeMemoryArtifact:
        artifact_type = self._resolve_artifact_type(item, source_tier)
        metadata = dict(item.get("metadata", {}) or {})
        # Never allow bridging to drop an explicit training prohibition.
        # Only an independent EchoCore admission assessment can approve.
        upstream = getattr(item.get("training_eligibility"), "value", item.get("training_eligibility"))
        nested = getattr(metadata.get("training_eligibility"), "value", metadata.get("training_eligibility"))
        eligibility = (
            "ineligible"
            if any(str(value or "").strip().lower() == "ineligible" for value in (upstream, nested))
            else "review"
        )
        return RuntimeMemoryArtifact(
            artifact_id=str(item.get("id") or item.get("artifact_id") or item.get("record_id")),
            artifact_type=artifact_type,
            source_tier=source_tier,
            user_id=str(item.get("user_id") or "anonymous"),
            tenant_id=item.get("tenant_id"),
            session_id=item.get("session_id"),
            thread_id=item.get("thread_id"),
            content=dict(item),
            importance_score=float(item.get("importance_score", 0.0) or 0.0),
            retention_score=float(item.get("retention_score", 0.0) or 0.0),
            privacy_tags=list(item.get("privacy_tags", []) or []),
            metadata=metadata,
            training_eligibility=eligibility,
        )

    def _items_from_result(self, write_result: Dict[str, Any], *keys: str) -> List[Dict[str, Any]]:
        for key in keys:
            items = write_result.get(key)
            if items:
                return list(items)
        return []

    def _resolve_artifact_type(
        self,
        item: Dict[str, Any],
        source_tier: MemoryTier,
    ) -> EchoArtifactType:
        raw_type = str(
            item.get("artifact_type")
            or item.get("record_type")
            or item.get("type")
            or ""
        ).lower()

        if raw_type in {EchoArtifactType.SHADOW_SIGNAL.value, "shadow"}:
            return EchoArtifactType.SHADOW_SIGNAL
        if raw_type in {EchoArtifactType.USER_PREFERENCE.value, "preference"}:
            return EchoArtifactType.USER_PREFERENCE
        if raw_type in {EchoArtifactType.PROJECT_MEMORY.value, "project"}:
            return EchoArtifactType.PROJECT_MEMORY
        if raw_type in {EchoArtifactType.EPISODIC_EVENT.value, "episodic"}:
            return EchoArtifactType.EPISODIC_EVENT
        if source_tier == MemoryTier.LTM:
            return EchoArtifactType.LONG_TERM_FACT
        if source_tier == MemoryTier.EPISODIC:
            return EchoArtifactType.EPISODIC_EVENT
        return EchoArtifactType.METADATA_SIGNAL


__all__ = [
    "RuntimeToEchoBridge",
    "DefaultRuntimeToEchoBridge",
]

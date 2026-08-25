from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ai_karen_engine.core.memory.memory_writeback import InteractionType
from ai_karen_engine.core.memory.neuro import (
    MemoryCandidate,
    MemoryClass,
    classify_memory_candidate,
)


@dataclass
class MigrationResult:
    migrated: int = 0
    quarantined: int = 0
    skipped: int = 0
    errors: int = 0


class NeuroVaultMigrator:
    """One-time migration helper from NeuroVault records into unified writeback flow."""

    def __init__(self, writeback_system: Any):
        self.writeback_system = writeback_system

    async def migrate_entries(self, entries: Iterable[dict[str, Any]]) -> MigrationResult:
        result = MigrationResult()
        for raw in entries:
            try:
                candidate = self._map_entry(raw)
                if not candidate:
                    result.skipped += 1
                    continue

                metadata = dict(candidate.metadata)
                metadata["provenance"] = candidate.provenance
                metadata["migrated_from"] = "neuro_vault"
                metadata["original_created_at"] = raw.get("created_at")
                metadata["original_updated_at"] = raw.get("updated_at")
                metadata["confidence"] = candidate.confidence
                metadata["importance"] = candidate.importance
                metadata["memory_class"] = candidate.memory_class.value

                await self.writeback_system.queue_writeback(
                    content=candidate.text,
                    interaction_type=InteractionType.SYSTEM_GENERATED,
                    user_id=candidate.user_id,
                    org_id=candidate.tenant_id,
                    metadata=metadata,
                )
                if candidate.memory_class == MemoryClass.QUARANTINE:
                    result.quarantined += 1
                else:
                    result.migrated += 1
            except Exception:
                result.errors += 1
        return result

    def _map_entry(self, raw: dict[str, Any]) -> MemoryCandidate | None:
        tenant_id = str(raw.get("tenant_id") or "")
        user_id = str(raw.get("user_id") or "")
        text = str(raw.get("content") or raw.get("text") or "").strip()
        if not tenant_id or not user_id or not text:
            return None

        nv_type = str(raw.get("memory_type") or raw.get("type") or "").lower()
        mapping = {
            "episodic": MemoryClass.EPISODIC,
            "semantic": MemoryClass.SEMANTIC,
            "procedural": MemoryClass.PROCEDURAL,
        }
        memory_class = mapping.get(nv_type, MemoryClass.QUARANTINE)

        metadata = dict(raw.get("metadata") or {})
        if raw.get("pii_scrubbed") is not None:
            metadata["pii_scrubbed"] = raw.get("pii_scrubbed")
        if nv_type in {"unsafe", "unknown"}:
            memory_class = MemoryClass.QUARANTINE

        candidate = MemoryCandidate(
            id=str(raw.get("id") or ""),
            text=text,
            memory_class=memory_class,
            source="neuro_vault",
            tenant_id=tenant_id,
            user_id=user_id,
            confidence=float(raw.get("confidence", 0.7) or 0.7),
            importance=float(raw.get("importance", 0.5) or 0.5),
            freshness=1.0,
            provenance={
                "source_store": "neuro_vault",
                "timestamp": raw.get("timestamp") or datetime.utcnow().isoformat(),
            },
            metadata=metadata,
        )
        candidate.memory_class = classify_memory_candidate(candidate)
        return candidate

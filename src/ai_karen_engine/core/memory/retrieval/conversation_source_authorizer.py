"""Repository-backed eligibility checks for source conversations.

This is deliberately not wired into NeuroRecall until memory writes attest the
source IDs independently of mutable metadata. Ownership alone cannot establish
that a derived memory really originated from the claimed source.
"""
from __future__ import annotations

from typing import Any

from ai_karen_engine.core.memory.retrieval.neuro_recall import RecallRequest
from ai_karen_engine.core.memory.types import MemoryEntry
from ai_karen_engine.services.database.repositories import ConversationRepository


class ConversationSourceAuthorizer:
    """Check the current canonical owner and persona scope of every source."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    async def authorize(self, memory: MemoryEntry, request: RecallRequest) -> bool:
        metadata = getattr(memory.metadata, "custom", None)
        if not isinstance(metadata, dict):
            return False
        # Explicit source IDs are evidence candidates, not proof of derivation.
        # Accept only the supported single-source schema. Other source types,
        # ACL revision schemes and mixed-source provenance remain denied.
        lineage: Any = metadata.get("source_lineage")
        if not isinstance(lineage, dict) or "derived_source_ids" in metadata:
            return False
        if set(lineage) != {"conversation_id", "source_type"}:
            return False
        if lineage.get("source_type") != "conversation":
            return False
        source_id = lineage.get("conversation_id")
        if not isinstance(source_id, str) or not source_id.strip():
            return False
        if source_id.strip() != source_id or len(source_id) > 128:
            return False
        if not request.tenant_id or not request.user_id:
            return False
        try:
            result = await self._repository.get_conversation(source_id, request.tenant_id)
        except Exception:
            return False
        if not result.success or result.data is None:
            return False
        conversation = result.data
        if str(conversation.user_id) != request.user_id:
            return False
        stored = conversation.metadata or {}
        if not isinstance(stored, dict):
            return False
        actual_persona = stored.get("persona_scope_id")
        if actual_persona != request.metadata.get("persona_filter"):
            return False
        # A deleted/revoked source cannot be released based on a cached label.
        if stored.get("revoked") is True or stored.get("deleted") is True:
            return False
        # Current ownership is necessary but not sufficient. The caller must
        # supply an independently attested source-to-memory binding, which the
        # existing memory persistence API does not yet expose. Deny for now.
        return False

"""Canonical construction for the unified memory service.

Construction belongs at composition edges. Domain consumers should receive a
memory capability and must not instantiate the legacy Web UI facade.
"""

from __future__ import annotations

from ai_karen_engine.core.memory.unified_memory_service import UnifiedMemoryService


def create_unified_memory_service() -> UnifiedMemoryService:
    """Build the production unified memory service with canonical dependencies."""
    from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
    from ai_karen_engine.database.client import MultiTenantPostgresClient

    return UnifiedMemoryService(
        db_client=MultiTenantPostgresClient(),
        embedding_manager=EmbeddingManager(),
    )

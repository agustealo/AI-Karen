"""Repository factory for KAREN's canonical data layer.

Wires PostgreSQL-backed implementations behind the repository contracts.
During migration, legacy adapters can be registered alongside canonical
ones for shadow reads and gradual cutover.
"""

from __future__ import annotations

import logging
from typing import Optional

from ai_karen_engine.services.database.repositories.base import Repository
from ai_karen_engine.services.database.repositories.memory_repository import MemoryRepository
from ai_karen_engine.services.database.repositories.postgres_memory_repository import (
    PostgresMemoryRepository,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    ConversationRepository,
)
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from ai_karen_engine.services.database.repositories.artifact_store import ArtifactStore
from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

logger = logging.getLogger(__name__)


class RepositoryFactory:
    """Factory for canonical repository implementations."""

    def __init__(
        self,
        session_factory,
        storage_client=None,
    ):
        self._session_factory = session_factory
        self._storage_client = storage_client
        self._memory: Optional[MemoryRepository] = None
        self._conversation: Optional[ConversationRepository] = None
        self._artifact: Optional[ArtifactStore] = None

    def create_memory_repository(self) -> MemoryRepository:
        if self._memory is None:
            self._memory = PostgresMemoryRepository(session_factory=self._session_factory)
            logger.info("Canonical MemoryRepository initialized (PostgreSQL + pgvector + FTS)")
        return self._memory

    def create_conversation_repository(self) -> ConversationRepository:
        if self._conversation is None:
            self._conversation = PostgresConversationRepository(
                session_factory=self._session_factory,
            )
            logger.info("Canonical ConversationRepository initialized (PostgreSQL)")
        return self._conversation

    def create_artifact_store(self) -> ArtifactStore:
        if self._artifact is None:
            if self._storage_client is None:
                logger.warning("ArtifactStore initialized without storage client; uploads/downloads will fail")
            self._artifact = SupabaseArtifactStore(
                session_factory=self._session_factory,
                storage_client=self._storage_client,
            )
            logger.info("Canonical ArtifactStore initialized (Supabase Storage + PostgreSQL)")
        return self._artifact

    async def health_check_all(self) -> dict:
        results = {}
        memory = self.create_memory_repository()
        conv = self.create_conversation_repository()
        artifact = self.create_artifact_store()

        results["memory"] = (await memory.health_check()).success
        results["conversation"] = (await conv.health_check()).success
        results["artifact"] = (await artifact.health_check()).success
        return results

"""
Elasticsearch Projection Worker for AI Karen Memory System.

Projects memory assertions into Elasticsearch for lexical and hybrid retrieval.

DEPRECATED: Elasticsearch is on the retirement path under DATA-CONVERGE-1.
Lexical search is handled by PostgreSQL FTS via MemoryRepository.
"""

import warnings
warnings.warn(
    "ElasticWorker is deprecated and will be removed in DATA-CONVERGE-1. "
    "Lexical search is now handled by PostgreSQL FTS via MemoryRepository.",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
from typing import Any, Dict, Optional
from ai_karen_engine.core.logging import get_logger

from .base import ProjectionWorker
from ai_karen_engine.clients.database.elastic_client import ElasticClient

logger = logging.getLogger(__name__)

class ElasticWorker(ProjectionWorker):
    """Worker responsible for Elasticsearch projections."""

    def __init__(self):
        super().__init__("elasticsearch")
        self.client = ElasticClient(index="memory_ledger_lexical")
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            # Trigger lazy connection
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.client._ensure_connected)
            self._initialized = True

    async def project(self, event_data: Dict[str, Any], assertion_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Index assertion content and metadata in Elasticsearch.
        """
        try:
            await self._ensure_initialized()
            
            event_id = str(event_data.get("event_id"))
            user_id = str(event_data.get("user_id"))
            tenant_id = str(event_data.get("tenant_id"))
            
            # Prepare document
            doc = {
                "event_id": event_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "source_type": event_data.get("source_type"),
                "scope": event_data.get("scope"),
                "timestamp": event_data.get("created_at"),
            }
            
            if assertion_data:
                doc.update({
                    "assertion_id": str(assertion_data.get("assertion_id")),
                    "content": assertion_data.get("content"),
                    "confidence": assertion_data.get("confidence"),
                    "valid_from": assertion_data.get("valid_from"),
                    "valid_to": assertion_data.get("valid_to"),
                })
            else:
                payload = event_data.get("payload", {})
                doc.update({
                    "content": payload.get("text"),
                    "signal_type": payload.get("type"),
                })

            if not doc.get("content"):
                logger.warning(f"No content to project for event {event_id} to Elasticsearch.")
                return True

            # Index in Elasticsearch
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None, 
                lambda: self.client._es.index(index=self.client.index, document=doc) if self.client._es else False
            )
            
            return True if success else False

        except Exception as e:
            logger.error(f"Error projecting to Elasticsearch for event {event_data.get('event_id')}: {e}")
            return False

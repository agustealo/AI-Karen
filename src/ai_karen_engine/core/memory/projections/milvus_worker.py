"""
Milvus Projection Worker for AI Karen Memory System.

Projects memory assertions into the Milvus vector database for semantic retrieval.

DEPRECATED: Milvus is on the retirement path under DATA-CONVERGE-1.
Memory assertions are stored directly in PostgreSQL memory_items with pgvector.
"""

import warnings
warnings.warn(
    "MilvusWorker is deprecated and will be removed in DATA-CONVERGE-1. "
    "Memory is now stored directly in PostgreSQL via MemoryRepository.",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
from typing import Any, Dict, Optional
from ai_karen_engine.core.logging import get_logger

from .base import ProjectionWorker
from ai_karen_engine.clients.database.milvus_client import MilvusClient
from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)

class MilvusWorker(ProjectionWorker):
    """Worker responsible for Milvus vector projections."""

    def __init__(self):
        super().__init__("milvus")
        # Initialize Milvus client with a specific collection for the new ledger
        self.client = MilvusClient(collection="memory_ledger_semantic", dim=768)
        self.embedding_manager = EmbeddingManager()
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            # Note: MilvusClient._ensure_connected is called internally by _using
            # but we might want to trigger it early.
            self._initialized = True

    async def project(self, event_data: Dict[str, Any], assertion_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Extract text, generate embedding, and store in Milvus.
        """
        try:
            await self._ensure_initialized()
            
            # 1. Determine content to embed
            content = ""
            event_id = str(event_data.get("event_id"))
            
            if assertion_data:
                content = assertion_data.get("content", "")
            else:
                # Fallback to event payload if no assertion data
                payload = event_data.get("payload", {})
                content = payload.get("text", "")

            if not content:
                logger.warning(f"No content to project for event {event_id} to Milvus.")
                return True # Nothing to do, consider it success
                
            # 2. Generate Embedding (distilbert-base-uncased is 768 dim)
            # EmbeddingManager.get_embedding is sync, we'll run in executor
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(None, self.embedding_manager.get_embedding, content)
            
            if not embedding:
                logger.error(f"Failed to generate embedding for event {event_id}")
                return False

            # 3. Store in Milvus
            # Note: The current MilvusClient schema is (user_id, embedding)
            # We'll use assertion_id or event_id as the primary key if we can update the client.
            # For now, we'll use the client's upsert if available or similar.
            
            # Since MilvusClient is mostly sync, we'll run it in executor
            def milvus_store():
                # We need a unique ID for the vector record.
                # If we have an assertion_id, use it.
                record_id = assertion_data.get("assertion_id") if assertion_data else event_id
                
                # Check if client has a method to store specific records
                # Looking at MilvusClient, it has store_persona which takes (user_id, embedding)
                # We might need to extend MilvusClient or use collection directly.
                
                with self.client._using() as alias:
                    from pymilvus import Collection
                    col = Collection(self.client.collection_name, using=alias)
                    
                    # Ensure record_id is a string of max length 64 as per common schemas
                    str_id = str(record_id)[:64]
                    
                    # The current schema in MilvusClient._ensure_collection is:
                    # name="user_id", dtype=DataType.VARCHAR, is_primary=True, auto_id=False, max_length=64
                    # name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim
                    
                    col.insert([
                        [str_id],
                        [embedding]
                    ])
                    col.flush()
                return True

            success = await loop.run_in_executor(None, milvus_store)
            return success

        except Exception as e:
            logger.error(f"Error projecting to Milvus for event {event_data.get('event_id')}: {e}")
            return False

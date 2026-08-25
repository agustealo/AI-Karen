"""
DuckDB Projection Worker for AI Karen Memory System.

Projects memory events into DuckDB for offline analytics and evaluation.
"""

import asyncio
import os
from typing import Any

from ai_karen_engine.core.logging import get_logger

from .base import ProjectionWorker

logger = get_logger(__name__)

class DuckDBWorker(ProjectionWorker):
    """Worker responsible for DuckDB analytics projections."""

    def __init__(self):
        super().__init__("duckdb")
        self.db_path = os.getenv("DUCKDB_ANALYTICS_PATH", "data/memory_analytics.duckdb")
        self._initialized = False

    async def _ensure_initialized(self):
        if not self._initialized:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._initialized = True

    async def project(self, event_data: dict[str, Any], assertion_data: dict[str, Any] | None = None) -> bool:
        """
        Store event data in DuckDB for analytical processing.
        """
        try:
            await self._ensure_initialized()
            
            # Using DuckDB for analytics export
            import duckdb
            
            # Use context manager for auto-close
            loop = asyncio.get_running_loop()
            
            def duckdb_op():
                conn = duckdb.connect(self.db_path)
                try:
                    # Ensure table exists
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS memory_analytics_events (
                            event_id VARCHAR,
                            tenant_id VARCHAR,
                            user_id VARCHAR,
                            source_type VARCHAR,
                            confidence DOUBLE,
                            event_type VARCHAR,
                            created_at TIMESTAMP
                        )
                    """)
                    
                    # Insert record
                    conn.execute("""
                        INSERT INTO memory_analytics_events 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(event_data.get("event_id")),
                        str(event_data.get("tenant_id")),
                        str(event_data.get("user_id")),
                        event_data.get("source_type"),
                        event_data.get("confidence", 1.0),
                        event_data.get("event_type"),
                        event_data.get("created_at")
                    ))
                    return True
                finally:
                    conn.close()

            success = await loop.run_in_executor(None, duckdb_op)
            return success

        except Exception as e:
            logger.error(f"Error projecting to DuckDB for event {event_data.get('event_id')}: {e}")
            return False

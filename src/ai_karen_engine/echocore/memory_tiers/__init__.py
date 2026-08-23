"""
Memory Tiers - Multi-tier memory management for EchoCore

Provides three tiers of memory storage:
- ShortTermMemory: Vector-based fast recall (in-memory)
- LongTermMemory: OLAP analytics and trends (DuckDB)
- PersistentMemory: Relational storage (PostgreSQL)
"""

from ai_karen_engine.echocore.memory_tiers.short_term_memory import (
    ShortTermMemory,
    MemoryVector,
    SearchResult
)

from ai_karen_engine.echocore.memory_tiers.long_term_memory import (
    LongTermMemory,
    AnalyticsQuery,
    TrendAnalysis
)

from ai_karen_engine.echocore.memory_tiers.persistent_memory import (
    PersistentMemory,
    UserData,
    InteractionRecord
)

__all__ = [
    # Short-term memory
    "ShortTermMemory",
    "MemoryVector",
    "SearchResult",
    # Long-term memory
    "LongTermMemory",
    "AnalyticsQuery",
    "TrendAnalysis",
    # Persistent memory
    "PersistentMemory",
    "UserData",
    "InteractionRecord",
]

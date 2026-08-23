"""Compatibility helpers for the AG-UI memory interface."""

from datetime import datetime
from typing import List, Optional, Tuple

from ai_karen_engine.api_routes.schemas.ag_ui import AGUIMemoryEntry, AGUIMemoryQuery
from ai_karen_engine.core.memory.memory_service import WebUIMemoryEntry, WebUIMemoryQuery


async def transform_ag_ui_query(query: AGUIMemoryQuery) -> WebUIMemoryQuery:
    """Convert an AG-UI memory query to the internal WebUIMemoryQuery format."""
    time_range: Optional[Tuple[datetime, datetime]] = None
    if query.time_range and len(query.time_range) == 2:
        start_ms, end_ms = query.time_range
        time_range = (
            datetime.fromtimestamp(start_ms / 1000),
            datetime.fromtimestamp(end_ms / 1000),
        )

    return WebUIMemoryQuery(
        text=query.query_text,
        session_id=query.session_id,
        tags=query.tags or [],
        time_range=time_range,
        top_k=query.top_k or 5,
        similarity_threshold=query.similarity_threshold or 0.7,
    )


def transform_web_ui_entries(entries: List[WebUIMemoryEntry]) -> List[AGUIMemoryEntry]:
    """Transform internal WebUIMemoryEntry objects to AG-UI response format."""
    results: List[AGUIMemoryEntry] = []
    for entry in entries:
        timestamp_ms = (
            int(entry.timestamp.timestamp() * 1000)
            if isinstance(entry.timestamp, datetime)
            else int(entry.timestamp * 1000)
        )
        results.append(
            AGUIMemoryEntry(
                id=str(entry.id),
                content=entry.content,
                timestamp=timestamp_ms,
                tags=entry.tags,
                similarity_score=entry.similarity_score,
                session_id=entry.session_id,
                user_id=entry.user_id,
            )
        )
    return results

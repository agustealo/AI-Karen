"""AG-UI specific data models for memory operations."""

from datetime import datetime
from typing import List, Optional, Tuple

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field, field_validator


class AGUIMemoryQuery(BaseModel):
    """Memory query format expected by the AG-UI frontend."""

    query_text: str = Field(..., alias="queryText", min_length=1, max_length=1000)
    session_id: Optional[str] = Field(None, alias="sessionId", max_length=100)
    tags: Optional[List[str]] = Field(None, description="Filter results by tags")
    time_range: Optional[Tuple[int, int]] = Field(
        None,
        alias="timeRange",
        description="Unix timestamp range in milliseconds [start, end]",
    )
    top_k: Optional[int] = Field(5, alias="topK", ge=1, le=100)
    similarity_threshold: Optional[float] = Field(
        0.7, alias="similarityThreshold", ge=0.0, le=1.0
    )

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return None
        return [tag.strip().lower() for tag in v if tag and tag.strip()]


class AGUIMemoryEntry(BaseModel):
    """Memory entry format returned to the AG-UI frontend."""

    id: str
    content: str
    timestamp: int
    tags: List[str] = Field(default_factory=list)
    similarity_score: Optional[float] = Field(None, alias="similarityScore")
    session_id: Optional[str] = Field(None, alias="sessionId")
    user_id: Optional[str] = Field(None, alias="userId")


class AGUIMemoryQueryResponse(BaseModel):
    """Response format for AG-UI memory queries."""

    memories: List[AGUIMemoryEntry]
    query_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        alias="queryTimestamp",
    )

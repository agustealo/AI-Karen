"""
UI Memory Models for AI-Karen

Web UI specific memory types and models.
These belong in the interfaces layer, not in Core.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field


class MemoryType(str, Enum):
    """Types of memory entries for web UI categorization."""

    GENERAL = "general"
    FACT = "fact"
    PREFERENCE = "preference"
    CONTEXT = "context"
    CONVERSATION = "conversation"
    INSIGHT = "insight"


class UISource(str, Enum):
    """Source UI types for tracking memory origin."""

    WEB = "web"
    DESKTOP = "desktop"
    API = "api"
    AG_UI = "ag_ui"


@dataclass
class WebUIMemoryEntry:
    """Extended memory entry with web UI specific fields."""

    id: str
    content: str
    ui_source: Optional[UISource] = None
    conversation_id: Optional[str] = None
    memory_type: MemoryType = MemoryType.GENERAL
    importance_score: int = 5
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    ai_generated: bool = False
    user_confirmed: bool = True
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with web UI fields."""
        return {
            "id": self.id,
            "content": self.content,
            "ui_source": self.ui_source.value if self.ui_source else None,
            "conversation_id": self.conversation_id,
            "memory_type": self.memory_type.value,
            "importance_score": self.importance_score,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "ai_generated": self.ai_generated,
            "user_confirmed": self.user_confirmed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WebUIMemoryQuery(BaseModel):
    """Query model for web UI memory operations."""

    model_config = ConfigDict(extra="ignore")

    query: Optional[str] = None
    ui_source: Optional[UISource] = None
    memory_type: Optional[MemoryType] = None
    conversation_id: Optional[str] = None
    limit: int = 20
    offset: int = 0
    sort_by: str = "created_at"
    sort_order: str = "desc"
    ai_generated_only: bool = False
    user_confirmed_only: bool = False

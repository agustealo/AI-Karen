"""
Profile Models for AI Karen Memory System.

Defines the structured representations of user and organizational profiles,
synthesized from durable memory assertions and facts.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CommunicationStyle(BaseModel):
    """Synthesized communication preferences."""
    tone: str = "professional"
    verbosity: str = "medium"
    technical_depth: str = "balanced"
    preferred_format: str = "markdown"
    directives: list[str] = Field(default_factory=list)

class UserPreference(BaseModel):
    """Specific user preferences."""
    topic: str
    value: Any
    confidence: float
    last_reinforced: datetime
    provenance_ids: list[uuid.UUID] = Field(default_factory=list)

class ProfileSummary(BaseModel):
    """Compact summary of a profile for runtime consumption."""
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    roles: list[str] = Field(default_factory=list)
    communication_style: CommunicationStyle = Field(default_factory=CommunicationStyle)
    top_preferences: dict[str, Any] = Field(default_factory=dict)
    active_constraints: list[str] = Field(default_factory=list)
    stable_facts_count: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"

class ProfileGrowth(BaseModel):
    """Tracks temporal evolution of the profile."""
    user_id: uuid.UUID
    facts_discovered: int = 0
    contradictions_resolved: int = 0
    reinforcements_tracked: int = 0
    first_seen: datetime
    last_interaction: datetime

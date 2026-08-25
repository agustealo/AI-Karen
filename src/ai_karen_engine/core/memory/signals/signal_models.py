"""
Signal Models for AI Karen Memory System.

Defines schemas for normalized memory signals.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemorySignal:
    """Normalized output from extraction."""
    text: str
    signal_type: str  # e.g., 'preference', 'entity', 'directive', 'workflow'
    confidence: float
    entities: list[dict[str, str]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    scope: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class ExtractionResult:
    """Result of the extraction pipeline."""
    signals: list[MemorySignal] = field(default_factory=list)
    processing_time_ms: float = 0.0
    status: str = "success"  # 'success', 'degraded', 'failed'
    errors: list[str] = field(default_factory=list)

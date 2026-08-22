"""
Canonical evidence and citation models for web intelligence.

This module owns the stable evidence representation so that search, crawl,
research, and UI layers do not invent their own ad-hoc source cards.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def content_hash(content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceItem:
    """
    Stable evidence record for one retrieved page/source.

    This is the atomic provenance unit. Full content is NOT stored here;
    callers store content separately and reference it via content_ref.
    """

    evidence_id: str
    source_url: str
    canonical_url: str
    title: str
    publisher: str
    retrieved_at: str
    published_at: Optional[str] = None
    content_type: Optional[str] = None
    excerpt: Optional[str] = None
    content_ref: Optional[str] = None
    crawl_ref: Optional[str] = None
    relevance_score: float = 0.0
    trust_signals: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """
    Stable citation linking a claim or response to evidence.
    """

    citation_id: str
    evidence_id: str
    claim_text: Optional[str] = None
    location: Optional[str] = None
    retrieved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceConflict:
    """
    Record of conflicting evidence from multiple sources.
    """

    conflict_id: str
    claim_id: str
    evidence_a: str
    evidence_b: str
    conflict_type: str
    resolution_status: str = "unresolved"
    metadata: Dict[str, Any] = field(default_factory=dict)

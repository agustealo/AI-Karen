"""
Memory Claims for AI-Karen

Manages memory claims with uncertainty, contradiction tracking,
and temporal validity.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim


class MemoryClaimStore:
    """
    Stores and manages memory claims.
    """

    def __init__(self):
        self._claims: dict[str, MemoryClaim] = {}
        self._by_subject: dict[str, list[str]] = {}

    def add(self, claim: MemoryClaim) -> str:
        """Add a memory claim."""
        claim_id = f"{claim.subject}:{claim.predicate}:{claim.object}"
        self._claims[claim_id] = claim
        if claim.subject not in self._by_subject:
            self._by_subject[claim.subject] = []
        self._by_subject[claim.subject].append(claim_id)
        return claim_id

    def get(self, claim_id: str) -> MemoryClaim | None:
        """Get a memory claim by ID."""
        return self._claims.get(claim_id)

    def get_by_subject(self, subject: str) -> list[MemoryClaim]:
        """Get all claims about a subject."""
        claim_ids = self._by_subject.get(subject, [])
        return [self._claims[cid] for cid in claim_ids if cid in self._claims]

    def supersede(self, claim_id: str, new_claim: MemoryClaim) -> None:
        """Supersede an existing claim with a new one."""
        if claim_id in self._claims:
            old = self._claims[claim_id]
            old.status = ClaimStatus.SUPERSEDED
            new_claim.supersedes = claim_id
            self.add(new_claim)

    def detect_contradictions(self, claim_id: str) -> list[str]:
        """Detect contradictions for a claim."""
        claim = self._claims.get(claim_id)
        if not claim:
            return []
        contradictions = []
        for other_id, other in self._claims.items():
            if other_id == claim_id:
                continue
            if (claim.subject == other.subject and
                claim.predicate == other.predicate and
                claim.object != other.object):
                contradictions.append(other_id)
                claim.contradiction_refs.append(other_id)
                other.contradiction_refs.append(claim_id)
        return contradictions

    def update_confidence(self, claim_id: str, new_confidence: float) -> None:
        """Update confidence of a claim."""
        if claim_id in self._claims:
            self._claims[claim_id].confidence = new_confidence
            self._claims[claim_id].last_confirmed = datetime.utcnow()

    def get_valid_claims(self, at: datetime | None = None) -> list[MemoryClaim]:
        """Get all valid claims at a given time."""
        return [c for c in self._claims.values() if c.is_valid(at)]

    def get_claims_by_status(self, status: ClaimStatus) -> list[MemoryClaim]:
        """Get all claims with a given status."""
        return [c for c in self._claims.values() if c.status == status]

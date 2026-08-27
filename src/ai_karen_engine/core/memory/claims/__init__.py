"""Cognitive memory claim store.

The store remains an in-process cognitive utility, not a persistence authority.
Temporal evolution decisions are delegated to MemoryTemporalEvolutionService so
claim semantics match the durable ledger's validity model.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ai_karen_engine.core.memory.contracts import ClaimStatus as ClaimStatus
from ai_karen_engine.core.memory.contracts import MemoryClaim as MemoryClaim
from ai_karen_engine.core.memory.temporal import (
    MemoryTemporalEvolutionService,
    TemporalEvolutionDecision,
    TemporalEvolutionKind,
)


class MemoryClaimStore:
    """Store cognitive claim versions and apply canonical temporal semantics."""

    def __init__(self) -> None:
        self._claims: dict[str, MemoryClaim] = {}
        self._by_subject: dict[str, list[str]] = {}
        self._temporal = MemoryTemporalEvolutionService()

    def add(self, claim: MemoryClaim) -> str:
        """Add or replace the same logical claim value for compatibility."""
        claim_id = f"{claim.subject}:{claim.predicate}:{claim.object}"
        self._claims[claim_id] = claim
        subject_claims = self._by_subject.setdefault(claim.subject, [])
        if claim_id not in subject_claims:
            subject_claims.append(claim_id)
        return claim_id

    def get(self, claim_id: str) -> MemoryClaim | None:
        return self._claims.get(claim_id)

    def get_by_subject(self, subject: str) -> list[MemoryClaim]:
        claim_ids = self._by_subject.get(subject, [])
        return [self._claims[cid] for cid in claim_ids if cid in self._claims]

    def evolve(
        self,
        claim_id: str,
        incoming: MemoryClaim,
        *,
        recorded_at: datetime | None = None,
    ) -> TemporalEvolutionDecision:
        """Evolve an existing claim through the canonical temporal authority."""
        previous = self._claims.get(claim_id)
        if previous is None:
            raise KeyError(f"unknown memory claim: {claim_id}")
        decision = self._temporal.evolve(
            previous,
            incoming,
            recorded_at=recorded_at,
        )
        self._claims[claim_id] = decision.previous
        self.add(decision.incoming)
        return decision

    def supersede(self, claim_id: str, new_claim: MemoryClaim) -> None:
        """Compatibility API for an explicit caller-directed supersession."""
        old = self._claims.get(claim_id)
        if old is None:
            return
        now = datetime.now(tz=timezone.utc)
        new_effective = self._temporal.effective_time(new_claim)
        old.status = ClaimStatus.SUPERSEDED
        old.superseded_at = now
        old.valid_until = min(old.valid_until, new_effective) if old.valid_until else new_effective
        new_claim.supersedes = self._temporal.claim_ref(old)
        if new_claim.valid_from is None:
            new_claim.valid_from = new_effective
        self.add(new_claim)

    def detect_contradictions(self, claim_id: str) -> list[str]:
        """Detect true temporal conflicts, excluding ordinary historical change."""
        claim = self._claims.get(claim_id)
        if claim is None:
            return []

        contradictions: list[str] = []
        for other_id, other in list(self._claims.items()):
            if other_id == claim_id:
                continue
            if claim.subject != other.subject or claim.predicate != other.predicate:
                continue
            if claim.object == other.object:
                continue
            try:
                decision = self._temporal.evolve(other, claim)
            except ValueError:
                continue
            if decision.kind is not TemporalEvolutionKind.CONTRADICT:
                continue
            contradictions.append(other_id)
            self._claims[other_id] = decision.previous
            self._claims[claim_id] = decision.incoming
            claim = decision.incoming
        return contradictions

    def update_confidence(self, claim_id: str, new_confidence: float) -> None:
        if claim_id in self._claims:
            self._claims[claim_id].confidence = max(0.0, min(1.0, new_confidence))
            self._claims[claim_id].last_confirmed = datetime.now(tz=timezone.utc)

    def get_valid_claims(self, at: datetime | None = None) -> list[MemoryClaim]:
        return [claim for claim in self._claims.values() if claim.is_valid(at)]

    def get_claims_by_status(self, status: ClaimStatus) -> list[MemoryClaim]:
        return [claim for claim in self._claims.values() if claim.status == status]


__all__ = ["ClaimStatus", "MemoryClaim", "MemoryClaimStore"]

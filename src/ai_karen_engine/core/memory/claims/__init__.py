"""Cognitive memory claim store.

The store is a single-tenant, single-owner in-process cognitive utility, not a
persistence or authorization authority. Callers must derive scope from an
authenticated runtime context, never from untrusted user input.
Temporal decisions delegate to MemoryTemporalEvolutionService.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_karen_engine.core.memory.contracts import ClaimStatus as ClaimStatus
from ai_karen_engine.core.memory.contracts import MemoryClaim as MemoryClaim
from ai_karen_engine.core.memory.temporal import (
    MemoryTemporalEvolutionService,
    TemporalEvolutionDecision,
    TemporalEvolutionKind,
)


class MemoryClaimStore:
    """Keep one tenant/owner's claim versions in one temporal snapshot scope."""

    def __init__(self, *, tenant_id: str, user_id: str | None) -> None:
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or tenant_id != tenant_id.strip()
            or tenant_id.casefold() == "default"
        ):
            raise ValueError("memory claim store requires an explicit tenant")
        if user_id is not None and (
            not isinstance(user_id, str)
            or not user_id
            or user_id != user_id.strip()
        ):
            raise ValueError("memory claim store user scope is invalid")
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._claims: dict[str, MemoryClaim] = {}
        self._by_subject: dict[str, list[str]] = {}
        self._temporal = MemoryTemporalEvolutionService()

    def _require_scope(self, *, tenant_id: str, user_id: str | None) -> None:
        """Reject accidental cross-scope access without disclosing scope IDs."""
        if tenant_id != self._tenant_id or user_id != self._user_id:
            raise ValueError("memory claim store scope mismatch")

    def _require_claim_scope(self, claim: MemoryClaim) -> None:
        self._require_scope(tenant_id=claim.tenant_id, user_id=claim.user_id)

    def _require_stored_identity(self, claim_id: str, claim: MemoryClaim) -> None:
        """Fail closed if a mutable stored claim no longer matches its key."""
        self._require_claim_scope(claim)
        if self._temporal.claim_ref(claim) != claim_id:
            raise ValueError("memory claim store identity mismatch")

    def _verified_items(self) -> list[tuple[str, MemoryClaim]]:
        """Prevalidate the full snapshot before any multi-claim operation."""
        items = list(self._claims.items())
        for claim_id, claim in items:
            self._require_stored_identity(claim_id, claim)
        return items

    def _checked_replacement_id(self, claim: MemoryClaim) -> str:
        """Reject a changed-owner record before replacing its logical key."""
        # Reuse the canonical owner-scoped and version-aware claim reference.
        # Raw delimiter concatenation aliases unrelated subject/predicate pairs.
        claim_id = self._temporal.claim_ref(claim)
        existing = self._claims.get(claim_id)
        if existing is not None:
            self._require_stored_identity(claim_id, existing)
        return claim_id

    def _require_free_destination(self, destination_id: str, source_id: str) -> None:
        """Deny version collisions before mutating a source claim."""
        if destination_id != source_id and destination_id in self._claims:
            raise ValueError("memory claim destination version already exists")

    def add(self, claim: MemoryClaim) -> str:
        """Add only claims owned by this store's immutable tenant/user scope."""
        self._require_claim_scope(claim)
        claim_id = self._checked_replacement_id(claim)
        existing = self._claims.get(claim_id)
        if existing is not None:
            if existing is claim:
                return claim_id
            raise ValueError(
                "memory claim version already exists; use temporal evolution"
            )
        self._claims[claim_id] = claim
        subject_claims = self._by_subject.setdefault(claim.subject, [])
        if claim_id not in subject_claims:
            subject_claims.append(claim_id)
        return claim_id

    def get(
        self, claim_id: str, *, tenant_id: str, user_id: str | None
    ) -> MemoryClaim | None:
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        claim = self._claims.get(claim_id)
        if claim is not None:
            self._require_stored_identity(claim_id, claim)
        return claim

    def get_by_subject(
        self, subject: str, *, tenant_id: str, user_id: str | None
    ) -> list[MemoryClaim]:
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        claims: list[MemoryClaim] = []
        for claim_id in self._by_subject.get(subject, []):
            claim = self._claims.get(claim_id)
            if claim is not None:
                self._require_stored_identity(claim_id, claim)
                claims.append(claim)
        return claims

    def evolve(
        self,
        claim_id: str,
        incoming: MemoryClaim,
        *,
        recorded_at: datetime | None = None,
    ) -> TemporalEvolutionDecision:
        """Evolve an existing claim through the canonical temporal authority."""
        self._require_claim_scope(incoming)
        previous = self._claims.get(claim_id)
        if previous is None:
            raise KeyError(f"unknown memory claim: {claim_id}")
        self._require_stored_identity(claim_id, previous)
        decision = self._temporal.evolve(
            previous,
            incoming,
            recorded_at=recorded_at,
        )
        self._require_claim_scope(decision.previous)
        self._require_claim_scope(decision.incoming)
        incoming_id = self._checked_replacement_id(decision.incoming)
        if incoming_id == claim_id and decision.kind is not TemporalEvolutionKind.REINFORCE:
            raise ValueError("non-reinforcement evolution cannot replace its source")
        self._require_free_destination(incoming_id, claim_id)
        self._claims[claim_id] = decision.previous
        if incoming_id != claim_id:
            self.add(decision.incoming)
        return decision

    def supersede(self, claim_id: str, new_claim: MemoryClaim) -> None:
        """Compatibility API for explicit, same-owner supersession."""
        self._require_claim_scope(new_claim)
        old = self._claims.get(claim_id)
        if old is None:
            return
        self._require_stored_identity(claim_id, old)
        replacement_id = self._checked_replacement_id(new_claim)
        if replacement_id == claim_id:
            raise ValueError("supersession requires a distinct claim version")
        self._require_free_destination(replacement_id, claim_id)
        # Validate legacy/offset timestamps before changing either object.
        # The canonical interval normalizes naive timestamps to UTC.
        prior_interval = self._temporal.interval(old)
        new_effective = self._temporal.effective_time(new_claim)
        if new_effective < self._temporal.effective_time(old):
            raise ValueError("backdated supersession requires temporal evolution")
        new_end = (
            min(prior_interval.end, new_effective)
            if prior_interval.end is not None
            else new_effective
        )
        now = datetime.now(tz=UTC)
        old.status = ClaimStatus.SUPERSEDED
        old.superseded_at = now
        old.valid_until = new_end
        new_claim.supersedes = self._temporal.claim_ref(old)
        if new_claim.valid_from is None:
            new_claim.valid_from = new_effective
        self.add(new_claim)

    def detect_contradictions(
        self, claim_id: str, *, tenant_id: str, user_id: str | None
    ) -> list[str]:
        """Detect same-owner temporal conflicts rather than historical changes."""
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        claim = self._claims.get(claim_id)
        if claim is None:
            return []
        self._require_stored_identity(claim_id, claim)

        contradictions: list[str] = []
        for other_id, other in self._verified_items():
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
            self._require_claim_scope(decision.previous)
            self._require_claim_scope(decision.incoming)
            contradictions.append(other_id)
            self._claims[other_id] = decision.previous
            self._claims[claim_id] = decision.incoming
            claim = decision.incoming
        return contradictions

    def update_confidence(
        self,
        claim_id: str,
        new_confidence: float,
        *,
        tenant_id: str,
        user_id: str | None,
    ) -> None:
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        claim = self._claims.get(claim_id)
        if claim is not None:
            self._require_stored_identity(claim_id, claim)
            claim.confidence = max(0.0, min(1.0, new_confidence))
            claim.last_confirmed = datetime.now(tz=UTC)

    def get_valid_claims(
        self,
        at: datetime | None = None,
        *,
        tenant_id: str,
        user_id: str | None,
    ) -> list[MemoryClaim]:
        """Use one coherent UTC snapshot for this authorized owner's claims."""
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        snapshot_at = at if at is not None else datetime.now(UTC)
        claims: list[MemoryClaim] = []
        for _, claim in self._verified_items():
            # An undated lookup means current-state retrieval, not an explicit
            # historical valid-time query. Keep the shared UTC snapshot for
            # every remaining claim without reviving superseded history.
            if at is None and claim.status is ClaimStatus.SUPERSEDED:
                continue
            if claim.is_valid(snapshot_at):
                claims.append(claim)
        return claims

    def get_claims_by_status(
        self,
        status: ClaimStatus,
        *,
        tenant_id: str,
        user_id: str | None,
    ) -> list[MemoryClaim]:
        self._require_scope(tenant_id=tenant_id, user_id=user_id)
        claims: list[MemoryClaim] = []
        for _, claim in self._verified_items():
            if claim.status == status:
                claims.append(claim)
        return claims


__all__ = ["ClaimStatus", "MemoryClaim", "MemoryClaimStore"]

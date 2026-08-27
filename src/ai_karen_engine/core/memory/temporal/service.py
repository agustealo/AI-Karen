"""Bi-temporal claim evolution for cognitive memory.

This module is deliberately persistence-neutral. It decides how a newly observed
claim relates to an existing claim version while preserving both valid time
(when a fact is true in the world) and record time (when KAREN learned or
processed it). Runtime/NeuroVault remain responsible for durable mutation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.memory.contracts import ClaimStatus, MemoryClaim


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TemporalInterval:
    """Half-open valid-time interval [start, end)."""

    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        start = _utc(self.start)
        end = _utc(self.end)
        if start is not None and end is not None and end < start:
            raise ValueError("temporal interval end cannot precede start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def overlaps(self, other: "TemporalInterval") -> bool:
        if self.end is not None and other.start is not None and self.end <= other.start:
            return False
        if other.end is not None and self.start is not None and other.end <= self.start:
            return False
        return True


@dataclass(frozen=True, slots=True)
class TemporalVersion:
    """Bi-temporal coordinates for a claim version."""

    valid_time: TemporalInterval
    recorded_at: datetime
    event_time: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recorded_at", _utc(self.recorded_at) or _now())
        object.__setattr__(self, "event_time", _utc(self.event_time))


class TemporalEvolutionKind(str, Enum):
    REINFORCE = "reinforce"
    SUPERSEDE = "supersede"
    CONTRADICT = "contradict"
    COEXIST = "coexist"


@dataclass(frozen=True, slots=True)
class TemporalEvolutionDecision:
    kind: TemporalEvolutionKind
    previous: MemoryClaim
    incoming: MemoryClaim
    previous_ref: str
    incoming_ref: str
    recorded_at: datetime
    reason: str


class MemoryTemporalEvolutionService:
    """Canonical decision authority for temporal claim evolution."""

    def evolve(
        self,
        previous: MemoryClaim,
        incoming: MemoryClaim,
        *,
        recorded_at: datetime | None = None,
    ) -> TemporalEvolutionDecision:
        recorded = _utc(recorded_at) or _now()
        self._validate_scope(previous, incoming)

        previous_ref = self.claim_ref(previous)
        incoming_ref = self.claim_ref(incoming)
        previous_interval = self.interval(previous)
        incoming_interval = self.interval(incoming)

        if previous.object == incoming.object:
            reinforced_previous = replace(
                previous,
                confidence=max(previous.confidence, incoming.confidence),
                last_confirmed=recorded,
                provenance=self._merge(previous.provenance, incoming.provenance),
                evidence=self._merge(previous.evidence, incoming.evidence),
                status=self._reinforced_status(previous.status, incoming.status),
            )
            reinforced_incoming = replace(
                incoming,
                last_confirmed=recorded,
                provenance=self._merge(previous.provenance, incoming.provenance),
                evidence=self._merge(previous.evidence, incoming.evidence),
            )
            return TemporalEvolutionDecision(
                kind=TemporalEvolutionKind.REINFORCE,
                previous=reinforced_previous,
                incoming=reinforced_incoming,
                previous_ref=previous_ref,
                incoming_ref=incoming_ref,
                recorded_at=recorded,
                reason="same_claim_value_reobserved",
            )

        if not previous_interval.overlaps(incoming_interval):
            return TemporalEvolutionDecision(
                kind=TemporalEvolutionKind.COEXIST,
                previous=previous,
                incoming=incoming,
                previous_ref=previous_ref,
                incoming_ref=incoming_ref,
                recorded_at=recorded,
                reason="different_values_do_not_overlap_in_valid_time",
            )

        previous_effective = self.effective_time(previous)
        incoming_effective = self.effective_time(incoming)
        if incoming_effective >= previous_effective:
            closed_at = incoming_interval.start or incoming_effective
            superseded_previous = replace(
                previous,
                valid_until=self._close_before(previous.valid_until, closed_at),
                superseded_at=recorded,
                status=ClaimStatus.SUPERSEDED,
            )
            superseding_incoming = replace(
                incoming,
                supersedes=previous_ref,
                valid_from=incoming.valid_from or incoming_effective,
            )
            return TemporalEvolutionDecision(
                kind=TemporalEvolutionKind.SUPERSEDE,
                previous=superseded_previous,
                incoming=superseding_incoming,
                previous_ref=previous_ref,
                incoming_ref=incoming_ref,
                recorded_at=recorded,
                reason="newer_overlapping_value_supersedes_previous_version",
            )

        previous_refs = self._merge(previous.contradiction_refs, [incoming_ref])
        incoming_refs = self._merge(incoming.contradiction_refs, [previous_ref])
        return TemporalEvolutionDecision(
            kind=TemporalEvolutionKind.CONTRADICT,
            previous=replace(
                previous,
                contradiction_refs=previous_refs,
                status=ClaimStatus.CONTRADICTED,
            ),
            incoming=replace(
                incoming,
                contradiction_refs=incoming_refs,
                status=ClaimStatus.DISPUTED,
            ),
            previous_ref=previous_ref,
            incoming_ref=incoming_ref,
            recorded_at=recorded,
            reason="backdated_overlapping_value_conflicts_with_current_version",
        )

    @staticmethod
    def interval(claim: MemoryClaim) -> TemporalInterval:
        start = claim.valid_from or claim.event_time or claim.asserted_at
        return TemporalInterval(start=start, end=claim.valid_until)

    @staticmethod
    def effective_time(claim: MemoryClaim) -> datetime:
        return _utc(claim.valid_from or claim.event_time or claim.asserted_at) or _now()

    @staticmethod
    def claim_ref(claim: MemoryClaim) -> str:
        payload: dict[str, Any] = {
            "tenant_id": claim.tenant_id,
            "user_id": claim.user_id,
            "subject": claim.subject,
            "predicate": claim.predicate,
            "object": claim.object,
            "asserted_at": _utc(claim.asserted_at).isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"claim:{digest}"

    @staticmethod
    def version(claim: MemoryClaim, *, recorded_at: datetime | None = None) -> TemporalVersion:
        recorded = _utc(recorded_at)
        if recorded is None:
            metadata_recorded = claim.metadata.get("recorded_at")
            if isinstance(metadata_recorded, datetime):
                recorded = _utc(metadata_recorded)
            elif isinstance(metadata_recorded, str) and metadata_recorded:
                try:
                    recorded = _utc(datetime.fromisoformat(metadata_recorded.replace("Z", "+00:00")))
                except ValueError:
                    recorded = None
        return TemporalVersion(
            valid_time=MemoryTemporalEvolutionService.interval(claim),
            event_time=claim.event_time,
            recorded_at=recorded or claim.asserted_at,
        )

    @staticmethod
    def _validate_scope(previous: MemoryClaim, incoming: MemoryClaim) -> None:
        if previous.tenant_id != incoming.tenant_id:
            raise ValueError("temporal claim evolution cannot cross tenant boundaries")
        if previous.user_id != incoming.user_id:
            raise ValueError("temporal claim evolution cannot cross user boundaries")
        if previous.subject != incoming.subject or previous.predicate != incoming.predicate:
            raise ValueError("temporal claim evolution requires the same subject and predicate")

    @staticmethod
    def _merge(left: list[str], right: list[str]) -> list[str]:
        return list(dict.fromkeys([*left, *right]))

    @staticmethod
    def _close_before(existing_end: datetime | None, candidate: datetime) -> datetime:
        candidate = _utc(candidate) or candidate
        existing = _utc(existing_end)
        if existing is None:
            return candidate
        return min(existing, candidate)

    @staticmethod
    def _reinforced_status(previous: ClaimStatus, incoming: ClaimStatus) -> ClaimStatus:
        rank = {
            ClaimStatus.UNKNOWN: 0,
            ClaimStatus.OBSERVED: 1,
            ClaimStatus.INFERRED: 1,
            ClaimStatus.USER_ASSERTED: 2,
            ClaimStatus.SUPPORTED: 3,
            ClaimStatus.VERIFIED: 4,
        }
        if rank.get(incoming, -1) > rank.get(previous, -1):
            return incoming
        return previous


__all__ = [
    "MemoryTemporalEvolutionService",
    "TemporalEvolutionDecision",
    "TemporalEvolutionKind",
    "TemporalInterval",
    "TemporalVersion",
]

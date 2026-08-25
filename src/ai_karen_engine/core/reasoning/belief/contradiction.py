"""
Contradiction detection for AI-Karen belief engine.

Distinguishes direct contradiction from temporal change (supersession).
Pure logic only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .contracts import (
    BeliefContradiction,
    ClaimStatus,
    ClaimTemporalValidity,
    ContradictionKind,
    ContradictionNature,
    Evidence,
    EvidenceRelation,
    EvidenceType,
    BeliefClaim,
    make_contradiction_id,
)

logger = logging.getLogger(__name__)


class ContradictionDetector:
    """Detects and classifies contradictions between claims and evidence."""

    TEMPORAL_SUPERSESSION_WINDOW: float = 30.0  # days

    def detect(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> List[BeliefContradiction]:
        """Detect contradictions between a claim and evidence items."""
        contradictions: List[BeliefContradiction] = []

        contradicting_evidence = self._find_contradicting_evidence(claim, evidence)
        for ev in contradicting_evidence:
            nature = self._determine_nature(claim, ev)
            kind = self._determine_kind(claim, ev)
            contradictions.append(
                BeliefContradiction(
                    contradiction_id=make_contradiction_id(),
                    claim_a_id=claim.claim_id,
                    claim_b_id=None,
                    kind=kind,
                    nature=nature,
                    severity=self._severity(ev),
                    description=self._contradiction_description(claim, ev, nature),
                    evidence_refs=[ev.evidence_id],
                    detected_at=datetime.utcnow(),
                    tenant_id=claim.tenant_id,
                )
            )

        return contradictions

    def compare_claims(
        self,
        claim_a: BeliefClaim,
        claim_b: BeliefClaim,
    ) -> Optional[BeliefContradiction]:
        """Compare two claims for contradiction."""
        if claim_a.tenant_id != claim_b.tenant_id:
            return None
        if claim_a.subject != claim_b.subject:
            if self._subjects_overlap(claim_a.subject, claim_b.subject):
                pass
            else:
                return None

        if claim_a.predicate == claim_b.predicate:
            if claim_a.object == claim_b.object:
                return None
            nature = self._temporal_nature(claim_a, claim_b)
            severity = "high" if nature == ContradictionNature.CONTRADICTION else "low"
            return BeliefContradiction(
                contradiction_id=make_contradiction_id(),
                claim_a_id=claim_a.claim_id,
                claim_b_id=claim_b.claim_id,
                kind=ContradictionKind.DIRECT if nature == ContradictionNature.CONTRADICTION else ContradictionKind.TEMPORAL,
                nature=nature,
                severity=severity,
                description=f"Claims disagree on {claim_a.predicate}: '{claim_a.object}' vs '{claim_b.object}'",
                detected_at=datetime.utcnow(),
                tenant_id=claim_a.tenant_id,
            )

        if self._claims_refer_to_same_subject(claim_a, claim_b):
            nature = self._temporal_nature(claim_a, claim_b)
            return BeliefContradiction(
                contradiction_id=make_contradiction_id(),
                claim_a_id=claim_a.claim_id,
                claim_b_id=claim_b.claim_id,
                kind=ContradictionKind.DIRECT,
                nature=nature,
                severity="medium",
                description=f"Related claims disagree: '{claim_a.predicate}' vs '{claim_b.predicate}'",
                detected_at=datetime.utcnow(),
                tenant_id=claim_a.tenant_id,
            )

        return None

    def detect_all(
        self,
        claims: List[BeliefClaim],
        evidence_map: Optional[Dict[str, List[Evidence]]] = None,
    ) -> List[BeliefContradiction]:
        """Detect contradictions within a set of claims and their evidence."""
        evidence_map = evidence_map or {}
        contradictions: List[BeliefContradiction] = []

        for claim in claims:
            evs = evidence_map.get(claim.claim_id, [])
            contradictions.extend(self.detect(claim, evs))

        for i, claim_a in enumerate(claims):
            for claim_b in claims[i + 1:]:
                result = self.compare_claims(claim_a, claim_b)
                if result:
                    contradictions.append(result)

        return contradictions

    def resolve_temporal(
        self,
        old_claim: BeliefClaim,
        new_claim: BeliefClaim,
    ) -> Tuple[ContradictionNature, Optional[BeliefClaim]]:
        """Determine if a new claim supersedes an old one (change over time)
        rather than directly contradicting it.

        Returns (nature, superseded_claim_or_none).
        """
        if old_claim.subject != new_claim.subject:
            return ContradictionNature.CONTRADICTION, None
        if old_claim.predicate != new_claim.predicate:
            return ContradictionNature.CONTRADICTION, None

        time_gap = self._time_gap(old_claim, new_claim)
        if time_gap >= self.TEMPORAL_SUPERSESSION_WINDOW:
            return ContradictionNature.CHANGE_OVER_TIME, new_claim

        if old_claim.object != new_claim.object:
            return ContradictionNature.CONTRADICTION, None

        return ContradictionNature.CHANGE_OVER_TIME, new_claim

    # ---- private helpers ----

    def _find_contradicting_evidence(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> List[Evidence]:
        return [
            e for e in evidence
            if e.relation in (EvidenceRelation.CONTRADICTS, EvidenceRelation.WEAKENS)
        ]

    def _determine_nature(self, claim: BeliefClaim, evidence: Evidence) -> ContradictionNature:
        """Determine if this is a true contradiction or a temporal change."""
        claim_time = claim.temporal.last_verified_at or claim.temporal.observed_at or claim.temporal.asserted_at
        ev_time = evidence.observed_at

        if claim_time is None or ev_time is None:
            return ContradictionNature.CONTRADICTION

        gap_days = abs((ev_time - claim_time).total_seconds()) / 86400.0
        if gap_days >= self.TEMPORAL_SUPERSESSION_WINDOW:
            return ContradictionNature.CHANGE_OVER_TIME

        return ContradictionNature.CONTRADICTION

    def _determine_kind(self, claim: BeliefClaim, evidence: Evidence) -> ContradictionKind:
        if evidence.type == EvidenceType.SYSTEM_INFERENCE:
            return ContradictionKind.SOURCE_DISAGREEMENT
        if claim.source == EvidenceType.USER_STATEMENT and evidence.type == EvidenceType.USER_STATEMENT:
            return ContradictionKind.SOURCE_DISAGREEMENT
        return ContradictionKind.DIRECT

    def _temporal_nature(self, claim_a: BeliefClaim, claim_b: BeliefClaim) -> ContradictionNature:
        """Determine temporal nature between two claims."""
        time_a = claim_a.temporal.last_verified_at or claim_a.temporal.observed_at or claim_a.temporal.asserted_at
        time_b = claim_b.temporal.last_verified_at or claim_b.temporal.observed_at or claim_b.temporal.asserted_at

        if time_a is None or time_b is None:
            return ContradictionNature.CONTRADICTION

        gap_days = abs((time_b - time_a).total_seconds()) / 86400.0
        if gap_days >= self.TEMPORAL_SUPERSESSION_WINDOW:
            return ContradictionNature.CHANGE_OVER_TIME

        return ContradictionNature.CONTRADICTION

    def _time_gap(self, old_claim: BeliefClaim, new_claim: BeliefClaim) -> float:
        """Days between old and new claim."""
        old_time = old_claim.temporal.last_verified_at or old_claim.temporal.asserted_at
        new_time = new_claim.temporal.last_verified_at or new_claim.temporal.asserted_at
        if old_time is None or new_time is None:
            return 0.0
        return abs((new_time - old_time).total_seconds()) / 86400.0

    def _subjects_overlap(self, subj_a: str, subj_b: str) -> bool:
        words_a = set(subj_a.lower().split())
        words_b = set(subj_b.lower().split())
        if len(words_a) == 0 or len(words_b) == 0:
            return subj_a == subj_b
        overlap = words_a & words_b
        min_len = min(len(words_a), len(words_b))
        return len(overlap) >= min_len / 2

    def _claims_refer_to_same_subject(
        self, claim_a: BeliefClaim, claim_b: BeliefClaim
    ) -> bool:
        return self._subjects_overlap(claim_a.subject, claim_b.subject)

    def _severity(self, evidence: Evidence) -> str:
        if evidence.strength == "definitive":
            return "critical"
        if evidence.strength == "strong":
            return "high"
        if evidence.strength == "moderate":
            return "medium"
        return "low"

    def _contradiction_description(
        self, claim: BeliefClaim, evidence: Evidence, nature: ContradictionNature
    ) -> str:
        if nature == ContradictionNature.CHANGE_OVER_TIME:
            return f"Claim '{claim.subject} {claim.predicate} {claim.object}' updated by newer evidence (temporal change)"
        return f"Evidence {evidence.evidence_id} contradicts claim '{claim.subject} {claim.predicate} {claim.object}'"


__all__ = ["ContradictionDetector"]

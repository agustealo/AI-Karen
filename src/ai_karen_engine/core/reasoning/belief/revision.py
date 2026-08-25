"""
Belief revision policy for AI-Karen.

Pure logic: determines how beliefs should be revised when new evidence arrives.
Never overwrites evidence silently; always preserves history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .contracts import (
    ClaimStatus,
    ContradictionNature,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
    BeliefAssessment,
    BeliefClaim,
    BeliefContradiction,
    BeliefRevision,
    ConfidenceMetrics,
    RevisionAction,
    make_revision_id,
)
from .assessment import BeliefEngine
from .contradiction import ContradictionDetector
from .temporal import TemporalReasoner

logger = logging.getLogger(__name__)


class BeliefRevisionEngine:
    """Applies revision actions to claims based on incoming evidence."""

    def __init__(
        self,
        engine: Optional[BeliefEngine] = None,
        detector: Optional[ContradictionDetector] = None,
        temporal: Optional[TemporalReasoner] = None,
    ) -> None:
        self._engine = engine or BeliefEngine()
        self._detector = detector or ContradictionDetector()
        self._temporal = temporal or TemporalReasoner()
        self._revision_history: List[BeliefRevision] = []

    def revise(
        self,
        claim: BeliefClaim,
        new_evidence: List[Evidence],
        existing_evidence: List[Evidence],
    ) -> Tuple[RevisionAction, BeliefRevision]:
        """Determine the revision action for a claim given new evidence."""
        all_evidence = existing_evidence + new_evidence
        contradictions = self._detector.detect(claim, all_evidence)

        has_contradiction = any(
            c.nature == ContradictionNature.CONTRADICTION for c in contradictions
        )
        has_temporal_change = any(
            c.nature == ContradictionNature.CHANGE_OVER_TIME for c in contradictions
        )

        if claim.status == ClaimStatus.RETRACTED:
            return self._apply(RevisionAction.KEEP, claim, None, 0.0, claim.confidence, "claim retracted")

        if has_temporal_change and claim.status in (
            ClaimStatus.OBSERVED,
            ClaimStatus.USER_ASSERTED,
            ClaimStatus.VERIFIED,
        ):
            return self._apply(
                RevisionAction.SUPERSEDE, claim, new_evidence[0] if new_evidence else None,
                self._revised_confidence(claim, all_evidence), claim.confidence,
                "temporal supersession by newer evidence",
            )

        if has_contradiction:
            if claim.status == ClaimStatus.VERIFIED:
                return self._apply(
                    RevisionAction.DISPUTE, claim, None, claim.confidence, claim.confidence,
                    "verified claim contradicted; requires verification",
                )
            elif claim.status == ClaimStatus.INFERRED:
                return self._apply(
                    RevisionAction.WEAKEN, claim, None,
                    max(0.0, claim.confidence - 0.3), claim.confidence,
                    "inferred claim contradicted",
                )
            else:
                return self._apply(
                    RevisionAction.WEAKEN, claim, None,
                    max(0.0, claim.confidence - 0.2), claim.confidence,
                    "claim contradicted; confidence reduced",
                )

        assessment = self._engine.assess(claim, all_evidence)
        if assessment.overall_confidence > claim.confidence + 0.1:
            return self._apply(
                RevisionAction.STRENGTHEN, claim, None,
                assessment.overall_confidence, claim.confidence,
                "corroborating evidence strengthens claim",
            )
        elif assessment.overall_confidence < claim.confidence - 0.1:
            if assessment.overall_confidence < 0.3:
                return self._apply(
                    RevisionAction.RETRACT, claim, None,
                    assessment.overall_confidence, claim.confidence,
                    "insufficient evidence after reassessment",
                )
            return self._apply(
                RevisionAction.WEAKEN, claim, None,
                assessment.overall_confidence, claim.confidence,
                "evidence does not support previous confidence",
            )

        return self._apply(RevisionAction.KEEP, claim, None, claim.confidence, claim.confidence, "no change needed")

    def merge(
        self,
        claim_a: BeliefClaim,
        claim_b: BeliefClaim,
    ) -> Optional[BeliefClaim]:
        """Merge two corroborating claims into one."""
        if claim_a.subject != claim_b.subject:
            return None
        if claim_a.predicate != claim_b.predicate:
            return None

        relationship = self._engine.compare(claim_a, claim_b, [])
        if relationship not in ("same", "corroborating"):
            return None

        merged_confidence = (claim_a.confidence + claim_b.confidence) / 2.0
        merged_evidence = list(set(claim_a.evidence_ids + claim_b.evidence_ids))
        merged_status = max(
            claim_a.status, claim_b.status,
            key=lambda s: ClaimStatus._value2member_map_.get(s, 0) if isinstance(s, str) else 0,
        )

        merged = BeliefClaim(
            claim_id=f"merged_{uuid.uuid4().hex[:12]}",
            subject=claim_a.subject,
            predicate=claim_a.predicate,
            object=claim_a.object,
            status=merged_status,
            source=claim_a.source,
            source_ref=claim_a.source_ref,
            scope=claim_a.scope,
            confidence=merged_confidence,
            tenant_id=claim_a.tenant_id,
            user_id=claim_a.user_id,
            claim_format=claim_a.claim_format,
            provenance=f"merged from {claim_a.claim_id} and {claim_b.claim_id}",
            evidence_ids=merged_evidence,
            contradictions=[],
            superseded_by=None,
            version=1,
        )
        return merged

    def verify(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> bool:
        """INFERRED claims cannot be auto-verified, but explicit verification can promote them."""
        if claim.status == ClaimStatus.INFERRED:
            assessment = self._engine.assess(claim, evidence)
            has_verification_evidence = any(
                e.type == EvidenceType.TOOL_RESULT
                and e.relation == EvidenceRelation.SUPPORTS
                and e.strength in (EvidenceStrength.STRONG, EvidenceStrength.DEFINITIVE)
                for e in evidence
            )
            if has_verification_evidence and assessment.overall_confidence >= 0.8:
                claim.status = ClaimStatus.VERIFIED
                return True
            return False

        if claim.status == ClaimStatus.SUPPORTED:
            assessment = self._engine.assess(claim, evidence)
            has_verification_evidence = any(
                e.type in (EvidenceType.TOOL_RESULT, EvidenceType.OBSERVATION)
                and e.relation == EvidenceRelation.SUPPORTS
                and e.strength in (EvidenceStrength.STRONG, EvidenceStrength.DEFINITIVE)
                for e in evidence
            )
            if has_verification_evidence and assessment.overall_confidence >= 0.85:
                claim.status = ClaimStatus.VERIFIED
                return True
            return False

        return claim.status == ClaimStatus.VERIFIED

    def supersede(
        self,
        old_claim: BeliefClaim,
        new_claim: BeliefClaim,
        reason: str = "",
    ) -> BeliefRevision:
        """Supersede an old claim with a new one. Preserves history."""
        old_claim.status = ClaimStatus.SUPERSEDED
        old_claim.superseded_by = new_claim.claim_id
        new_claim.temporal = old_claim.temporal

        revision = BeliefRevision(
            revision_id=make_revision_id(),
            claim_id=old_claim.claim_id,
            action=RevisionAction.SUPERSEDE,
            reason=reason or "new information supersedes prior claim",
            evidence_ref=new_claim.claim_id,
            confidence_before=old_claim.confidence,
            confidence_after=new_claim.confidence,
            tenant_id=old_claim.tenant_id,
            superseded_claim_id=new_claim.claim_id,
        )
        self._revision_history.append(revision)
        return revision

    def retract(
        self,
        claim: BeliefClaim,
        reason: str = "",
    ) -> BeliefRevision:
        """Retract a claim. History is preserved."""
        claim.status = ClaimStatus.RETRACTED
        claim.confidence = 0.0

        revision = BeliefRevision(
            revision_id=make_revision_id(),
            claim_id=claim.claim_id,
            action=RevisionAction.RETRACT,
            reason=reason or "claim retracted",
            evidence_ref=None,
            confidence_before=claim.confidence,
            confidence_after=0.0,
            tenant_id=claim.tenant_id,
        )
        self._revision_history.append(revision)
        return revision

    def revision_history(self, claim_id: str) -> List[BeliefRevision]:
        return [r for r in self._revision_history if r.claim_id == claim_id]

    def all_revisions(self) -> List[BeliefRevision]:
        return list(self._revision_history)

    # ---- private helpers ----

    def _apply(
        self,
        action: RevisionAction,
        claim: BeliefClaim,
        evidence: Optional[Evidence],
        new_confidence: float,
        old_confidence: float,
        reason: str,
    ) -> Tuple[RevisionAction, BeliefRevision]:
        new_confidence = max(0.0, min(1.0, new_confidence))
        ev_ref = evidence.evidence_id if evidence else None
        revision = BeliefRevision(
            revision_id=make_revision_id(),
            claim_id=claim.claim_id,
            action=action,
            reason=reason,
            evidence_ref=ev_ref,
            confidence_before=old_confidence,
            confidence_after=new_confidence,
            tenant_id=claim.tenant_id,
            superseded_claim_id=None,
        )
        self._revision_history.append(revision)
        claim.confidence = new_confidence
        return action, revision

    def _revised_confidence(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> float:
        assessment = self._engine.assess(claim, evidence)
        return assessment.overall_confidence


__all__ = ["BeliefRevisionEngine"]

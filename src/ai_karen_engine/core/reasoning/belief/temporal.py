"""
Temporal truth models for AI-Karen belief engine.

Every belief must support temporal validity.  Record creation time does not
equal fact validity time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import (
    ClaimStatus,
    BeliefClaim,
    ClaimTemporalValidity,
    Evidence,
)

logger = logging.getLogger(__name__)


class TemporalReasoner:
    """Evaluates temporal validity of belief claims."""

    def is_valid(
        self,
        claim: BeliefClaim,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check whether a claim is temporally valid at the given time."""
        now = now or datetime.utcnow()
        tv = claim.temporal

        if tv.valid_from is not None and now < tv.valid_from:
            return False
        if tv.valid_until is not None and now > tv.valid_until:
            return False
        if tv.is_expired(now):
            return False

        return True

    def is_stale(
        self,
        claim: BeliefClaim,
        threshold_hours: float = 24.0 * 7,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check if a claim is stale (not verified recently enough)."""
        now = now or datetime.utcnow()
        age = claim.temporal.age_seconds(now)
        return age > threshold_hours * 3600.0

    def effective_time(self, claim: BeliefClaim) -> Optional[datetime]:
        """The most recent temporal reference for a claim."""
        return (
            claim.temporal.last_verified_at
            or claim.temporal.observed_at
            or claim.temporal.asserted_at
        )

    def supersede_temporal(
        self,
        old_claim: BeliefClaim,
        new_observed_at: datetime,
    ) -> ClaimTemporalValidity:
        """Build a new temporal validity that supersedes the old one."""
        return ClaimTemporalValidity(
            asserted_at=new_observed_at,
            observed_at=new_observed_at,
            valid_from=new_observed_at,
            valid_until=None,
            last_verified_at=new_observed_at,
        )

    def age_hours(self, claim: BeliefClaim, now: Optional[datetime] = None) -> float:
        """Return the age of the claim in hours."""
        now = now or datetime.utcnow()
        age = claim.temporal.age_seconds(now)
        if age == float("inf"):
            return float("inf")
        return age / 3600.0

    def is_current(
        self,
        claim: BeliefClaim,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check if the claim reflects current reality (not stale)."""
        return not self.is_stale(claim, now=now)

    def temporal_distance(
        self,
        claim_a: BeliefClaim,
        claim_b: BeliefClaim,
    ) -> float:
        """Hours between the effective times of two claims."""
        ta = self.effective_time(claim_a)
        tb = self.effective_time(claim_b)
        if ta is None or tb is None:
            return float("inf")
        return abs((tb - ta).total_seconds()) / 3600.0

    def validate_temporal_consistency(
        self,
        claim: BeliefClaim,
        evidence: List[Evidence],
    ) -> List[str]:
        """Return list of temporal consistency violations."""
        violations: List[str] = []
        now = datetime.utcnow()

        if not self.is_valid(claim, now):
            violations.append("claim_outside_valid_window")

        if self.is_stale(claim, now=now):
            violations.append("claim_stale")

        for ev in evidence:
            if ev.observed_at is None:
                continue
            if ev.expires_at is not None and now > ev.expires_at:
                violations.append(f"evidence_{ev.evidence_id}_expired")

        claim_time = self.effective_time(claim)
        if claim_time is not None:
            for ev in evidence:
                if ev.observed_at is not None and ev.observed_at > claim_time:
                    pass  # evidence can be after claim (supports revision)

        return violations


__all__ = ["TemporalReasoner"]

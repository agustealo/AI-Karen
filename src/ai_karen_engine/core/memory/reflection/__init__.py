"""
Reflection Engine for AI-Karen

Derives knowledge from experience through reflection.
Implements evidence checking and promotion/defer/reject gates.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime, timezone

from ai_karen_engine.core.memory.contracts import MemoryClaim
from ai_karen_engine.core.memory.types import CognitiveMemoryEntry, ReflectionCandidate


class ReflectionEngine:
    """
    Derives knowledge from experience.

    Process:
    1. Collect recent meaningful episodes
    2. Identify patterns
    3. Generate candidate insights
    4. Check evidence
    5. Promote / Defer / Reject
    """

    def __init__(
        self,
        min_evidence_count: int = 3,
        min_confidence: float = 0.7,
        reflection_interval_hours: int = 24,
    ):
        self.min_evidence_count = min_evidence_count
        self.min_confidence = min_confidence
        self.reflection_interval_hours = reflection_interval_hours
        self._last_reflection: datetime | None = None

    async def reflect(self, episodes: list[CognitiveMemoryEntry]) -> list[ReflectionCandidate]:
        """
        Reflect on episodes to derive candidate insights.
        """
        candidates = []
        # Group episodes by subject/predicate
        grouped = self._group_episodes(episodes)

        for group in grouped.values():
            if len(group) < self.min_evidence_count:
                continue

            candidate = self._generate_candidate(group)
            if candidate:
                candidates.append(candidate)

        return candidates

    def _group_episodes(self, episodes: list[CognitiveMemoryEntry]) -> dict[str, list[CognitiveMemoryEntry]]:
        """Group episodes by subject for pattern detection."""
        groups: dict[str, list[CognitiveMemoryEntry]] = {}
        for ep in episodes:
            if ep.claim:
                key = f"{ep.claim.subject}:{ep.claim.predicate}"
                groups.setdefault(key, []).append(ep)
        return groups

    def _generate_candidate(self, episodes: list[CognitiveMemoryEntry]) -> ReflectionCandidate | None:
        """Generate a reflection candidate from a group of episodes."""
        if not episodes:
            return None

        first = episodes[0]
        claim = first.claim
        if not claim:
            return None

        confidence = min(1.0, claim.confidence + 0.1 * len(episodes))
        candidate = ReflectionCandidate(
            source_episodes=[ep.base_entry.id for ep in episodes],
            candidate_claim=MemoryClaim(
                subject=claim.subject,
                predicate=claim.predicate,
                object=claim.object,
                confidence=confidence,
                provenance=[p for ep in episodes for p in (ep.claim.provenance if ep.claim else [])],
                evidence=[ep.base_entry.id for ep in episodes],
                asserted_at=datetime.now(tz=timezone.utc),
                status=claim.status,
            ),
            evidence_count=len(episodes),
            confidence=confidence,
        )
        return candidate

    def evaluate_candidate(self, candidate: ReflectionCandidate) -> str:
        """
        Evaluate a reflection candidate.

        Returns: promoted, deferred, or rejected
        """
        if candidate.evidence_count < self.min_evidence_count:
            return "deferred"
        if candidate.confidence < self.min_confidence:
            return "rejected"
        if candidate.evidence_count >= self.min_evidence_count * 2:
            return "promoted"
        return "deferred"

    def should_reflect(self) -> bool:
        """Check if reflection should run."""
        if self._last_reflection is None:
            return True
        elapsed = (datetime.now(tz=timezone.utc) - self._last_reflection).total_seconds() / 3600.0
        return elapsed >= self.reflection_interval_hours

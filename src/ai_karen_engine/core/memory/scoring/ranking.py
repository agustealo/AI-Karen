"""Ranking for the AI Karen memory system.

Ranks retrieved memory candidates based on retrieval relevance, confidence, and
recency contribution. The ranker is a pure cognitive scoring component and has
no runtime, provider, persistence, or observability authority.
"""

from __future__ import annotations

from typing import Any


class MemoryRanker:
    """Rank memory items for context assembly."""

    def rank(
        self,
        candidates: list[dict[str, Any]],
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Rank candidates using the canonical combined score."""

        del query  # Reserved for future query-aware ranking without changing the API.

        for candidate in candidates:
            base_score = float(candidate.get("retrieval_score", 0.5))
            confidence = float(candidate.get("confidence", 1.0))

            # Current cognitive contract gives recency a neutral contribution.
            # Temporal decay belongs to the owning temporal/scoring policy, not
            # an implicit wall-clock lookup inside this ranker.
            recency_multiplier = 1.0

            candidate["final_rank_score"] = (
                base_score * 0.5
                + confidence * 0.3
                + recency_multiplier * 0.2
            )

        return sorted(
            candidates,
            key=lambda candidate: float(candidate.get("final_rank_score", 0.0)),
            reverse=True,
        )

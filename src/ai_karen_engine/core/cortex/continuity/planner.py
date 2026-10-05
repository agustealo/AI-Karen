"""Pure CORTEX ranking for predictive continuity.

The planner decides which current user-state items may be useful to surface.
It never reads databases, mutates state, invokes tools, creates reminders, or
authorizes execution.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .contracts import (
    ContinuityPlan,
    ContinuityStateItem,
    ContinuitySuggestion,
)


class ContinuityPlanner:
    """Rank likely next needs from governed continuity state."""

    _DIRECT_CUES = (
        "continue",
        "what next",
        "what should i do next",
        "what should we do next",
        "next step",
        "next steps",
        "what is left",
        "what's left",
        "unfinished",
        "still need",
        "follow up",
        "coming up",
        "upcoming",
        "what am i working on",
        "what are we working on",
    )
    _STOP_TERMS = {
        "what",
        "when",
        "where",
        "with",
        "that",
        "this",
        "have",
        "about",
        "should",
        "next",
        "step",
        "steps",
        "need",
        "still",
        "continue",
    }

    @classmethod
    def should_plan(cls, query: str) -> bool:
        normalized = str(query or "").strip().casefold()
        return any(cue in normalized for cue in cls._DIRECT_CUES)

    def plan(
        self,
        *,
        query: str,
        items: list[ContinuityStateItem],
        now: datetime | None = None,
        top_k: int = 5,
        context: dict[str, object] | None = None,
    ) -> ContinuityPlan:
        """Return bounded, explainable suggestions without execution authority."""

        if not self.should_plan(query):
            return ContinuityPlan(reason_codes=("continuity_not_requested",))

        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)

        ranked: list[ContinuitySuggestion] = []
        for item in items:
            score, reason_codes = self._score(
                query=query,
                item=item,
                now=reference,
                context=context or {},
            )
            if score <= 0.0:
                continue
            ranked.append(
                ContinuitySuggestion(
                    suggestion_id=self._suggestion_id(item),
                    source_type=item.source_type,
                    source_ref=item.item_id,
                    description=item.description,
                    score=score,
                    confidence=max(0.0, min(1.0, item.confidence)),
                    reason_codes=tuple(reason_codes),
                    target_at=item.target_at,
                    domain=item.domain,
                )
            )

        ranked.sort(
            key=lambda item: (
                item.score,
                item.confidence,
                item.target_at is not None,
                item.source_ref,
            ),
            reverse=True,
        )
        bounded = max(1, min(int(top_k), 10))
        selected = tuple(ranked[:bounded])
        return ContinuityPlan(
            suggestions=selected,
            reason_codes=(
                ("ranked_continuity_state",)
                if selected
                else ("no_relevant_continuity_state",)
            ),
            considered_count=len(items),
        )

    def _score(
        self,
        *,
        query: str,
        item: ContinuityStateItem,
        now: datetime,
        context: dict[str, object],
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        source = item.source_type.casefold()
        state = item.lifecycle_state.casefold()
        if state == "paused":
            return 0.0, []
        if state in {
            "completed",
            "cancelled",
            "abandoned",
            "superseded",
            "expired",
            "archived",
        }:
            return 0.0, []

        if source == "open_loop":
            score += 0.50
            reasons.append("unfinished_work")
        elif source == "prospective":
            score += 0.42
            reasons.append("upcoming_event")
        elif source == "goal":
            score += 0.34
            reasons.append("active_goal")
        else:
            return 0.0, []

        temporal = self._temporal_score(item.target_at, now)
        if temporal > 0.0:
            score += 0.28 * temporal
            if item.target_at is not None and self._is_due(item.target_at, now):
                reasons.append("due_or_overdue")
            else:
                reasons.append("near_term" if temporal >= 0.7 else "time_relevant")

        overlap = self._text_overlap(query, item.description)
        if item.domain:
            overlap = max(overlap, self._text_overlap(query, item.domain))
        if overlap > 0.0:
            score += 0.18 * overlap
            reasons.append("context_match")

        current_domain = str(
            context.get("domain") or context.get("current_domain") or ""
        ).strip().casefold()
        if item.domain and current_domain and item.domain.casefold() == current_domain:
            score += 0.12
            reasons.append("current_domain")

        current_project = str(
            context.get("project_id") or context.get("current_project_id") or ""
        ).strip()
        item_project = str(item.metadata.get("project_id") or "").strip()
        if current_project and item_project and current_project == item_project:
            score += 0.12
            reasons.append("current_project")

        confidence = max(0.0, min(1.0, item.confidence))
        score += 0.04 * confidence
        if confidence >= 0.9:
            reasons.append("high_confidence")

        if state in {"blocked", "at_risk"}:
            score += 0.08
            reasons.append("needs_attention")

        return min(1.0, score), reasons

    @staticmethod
    def _temporal_score(target_at: datetime | None, now: datetime) -> float:
        if target_at is None:
            return 0.0
        target = target_at
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        seconds = (target - now).total_seconds()
        if seconds <= 0:
            return 1.0
        hours = seconds / 3600.0
        if hours <= 24:
            return 1.0
        if hours <= 72:
            return 0.8
        if hours <= 168:
            return 0.55
        if hours <= 720:
            return 0.25
        return 0.0

    @staticmethod
    def _is_due(target_at: datetime, now: datetime) -> bool:
        target = target_at
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return target <= now

    @classmethod
    def _terms(cls, text: str) -> set[str]:
        return {
            token
            for token in re.findall(
                r"[\w'-]{3,}",
                str(text or "").casefold(),
                flags=re.UNICODE,
            )
            if token not in cls._STOP_TERMS
        }

    @classmethod
    def _text_overlap(cls, left: str, right: str) -> float:
        left_terms = cls._terms(left)
        right_terms = cls._terms(right)
        if not left_terms or not right_terms:
            return 0.0
        return len(left_terms & right_terms) / max(len(left_terms), 1)

    @staticmethod
    def _suggestion_id(item: ContinuityStateItem) -> str:
        digest = hashlib.sha256(
            f"{item.source_type}:{item.item_id}".encode("utf-8")
        ).hexdigest()[:16]
        return f"cont_{digest}"


__all__ = ["ContinuityPlanner"]

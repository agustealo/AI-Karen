"""Explainable proactive continuity ranking.

Ranks likely next needs from durable evidence. This service is read-only and
cannot execute actions, mutate user state, or create reminders/automations.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .contracts import (
    ContinuityEvidence,
    NextNeedCandidate,
    ProactiveContinuityRepository,
)


class ProactiveContinuityService:
    """Rank likely next needs from current user-state evidence."""

    def __init__(self, repository: ProactiveContinuityRepository) -> None:
        if repository is None:
            raise ValueError("proactive continuity requires an explicit repository")
        self._repository = repository

    async def rank(
        self,
        *,
        tenant_id: str,
        user_id: str,
        now: datetime | None = None,
        limit: int = 5,
    ) -> list[NextNeedCandidate]:
        now_utc = self._utc(now or datetime.now(timezone.utc))
        evidence = await self._repository.load_evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=max(20, min(int(limit) * 10, 200)),
        )

        ranked = [
            self._candidate(item, now=now_utc)
            for item in evidence
        ]
        ranked = [
            candidate
            for candidate in ranked
            if candidate is not None and candidate.utility >= 0.5
        ]
        ranked.sort(
            key=lambda item: (
                item.utility,
                item.confidence,
                -(item.interruption_cost),
            ),
            reverse=True,
        )

        deduped: list[NextNeedCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in ranked:
            key = (
                candidate.source_type,
                self._normalize_subject(candidate.subject),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
            if len(deduped) >= max(1, min(int(limit), 10)):
                break
        return deduped

    def _candidate(
        self,
        item: ContinuityEvidence,
        *,
        now: datetime,
    ) -> NextNeedCandidate | None:
        source = item.source_type
        state = str(item.state or "").casefold()
        confidence = max(0.0, min(1.0, float(item.confidence or 0.0)))
        reason_codes: list[str] = []
        utility = 0.0
        interruption_cost = 0.25
        urgency = "normal"

        if source == "open_loop":
            utility = 0.68
            reason_codes.append("unfinished_work")
            if state != "open":
                return None
        elif source == "prospective":
            utility = 0.72
            reason_codes.append("upcoming_event")
            if state not in {"dormant", "ready", "triggered"}:
                return None
        elif source == "goal":
            utility = 0.58
            reason_codes.append("active_goal")
            if state == "at_risk":
                utility += 0.18
                urgency = "high"
                reason_codes.append("goal_at_risk")
            elif state == "blocked":
                utility += 0.1
                reason_codes.append("goal_blocked")
            elif state not in {"active", "blocked", "paused", "at_risk", "satisfied"}:
                return None
        elif source == "behavior":
            if item.observation_count < 3 or confidence < 0.6:
                return None
            utility = 0.48 + min(0.18, 0.03 * item.observation_count)
            interruption_cost = 0.35
            reason_codes.extend(("recurring_behavior", "behavior_repeated"))
        else:
            return None

        time_utility, time_urgency, time_reasons = self._time_adjustment(
            item.target_at,
            now=now,
        )
        utility += time_utility
        if time_urgency is not None:
            urgency = time_urgency
        reason_codes.extend(time_reasons)

        if item.domain:
            reason_codes.append("domain_scoped")

        utility = max(0.0, min(1.0, utility))
        candidate_id = self._candidate_id(item)

        return NextNeedCandidate(
            candidate_id=candidate_id,
            source_type=source,
            source_id=item.source_id,
            subject=item.subject,
            utility=utility,
            confidence=confidence,
            urgency=urgency,
            interruption_cost=interruption_cost,
            target_at=self._utc(item.target_at) if item.target_at else None,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            metadata={
                **dict(item.metadata),
                "state": state,
                "domain": item.domain,
                "observation_count": item.observation_count,
                "response_mode": "suggest_only",
                "execution_authorized": False,
            },
        )

    @staticmethod
    def _time_adjustment(
        target_at: datetime | None,
        *,
        now: datetime,
    ) -> tuple[float, str | None, list[str]]:
        if target_at is None:
            return 0.0, None, []

        target = ProactiveContinuityService._utc(target_at)
        delta = target - now
        if delta < timedelta(hours=-1):
            return 0.12, "high", ["overdue"]
        if delta <= timedelta(hours=6):
            return 0.22, "high", ["due_soon"]
        if delta <= timedelta(days=1):
            return 0.16, "high", ["due_within_day"]
        if delta <= timedelta(days=3):
            return 0.1, "normal", ["due_within_three_days"]
        if delta <= timedelta(days=7):
            return 0.05, "low", ["due_within_week"]
        return 0.0, "low", ["future"]

    @staticmethod
    def _candidate_id(item: ContinuityEvidence) -> str:
        raw = f"{item.source_type}:{item.source_id}:{item.subject}".encode("utf-8")
        return f"next-{hashlib.sha256(raw).hexdigest()[:20]}"

    @staticmethod
    def _normalize_subject(value: str) -> str:
        return " ".join(str(value or "").casefold().split())

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = ["ProactiveContinuityService"]

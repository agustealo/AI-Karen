from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.core.intelligence.proactive import (
    ContinuityEvidence,
    ProactiveContinuityRepository,
    ProactiveContinuityService,
)


class _Repository(ProactiveContinuityRepository):
    def __init__(self, evidence: list[ContinuityEvidence]) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str, int]] = []

    async def load_evidence(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[ContinuityEvidence]:
        self.calls.append((tenant_id, user_id, limit))
        return list(self.evidence)


@pytest.mark.asyncio
async def test_open_loop_and_due_event_rank_ahead_of_weak_behavior() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="behavior",
                source_id="b1",
                subject="check project board",
                state="recurring",
                confidence=0.65,
                observation_count=3,
            ),
            ContinuityEvidence(
                source_type="open_loop",
                source_id="o1",
                subject="send the client the revised estimate",
                state="open",
                confidence=0.95,
            ),
            ContinuityEvidence(
                source_type="prospective",
                source_id="p1",
                subject="job interview with Ford",
                state="dormant",
                confidence=0.96,
                target_at=now + timedelta(hours=3),
            ),
        ]
    )

    ranked = await ProactiveContinuityService(repo).rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        now=now,
        limit=5,
    )

    assert [item.source_id for item in ranked[:2]] == ["p1", "o1"]
    assert ranked[0].urgency == "high"
    assert ranked[0].metadata["execution_authorized"] is False


@pytest.mark.asyncio
async def test_at_risk_goal_is_promoted_but_completed_state_is_ignored() -> None:
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="goal",
                source_id="g1",
                subject="prepare for certification",
                state="at_risk",
                confidence=0.9,
            ),
            ContinuityEvidence(
                source_type="goal",
                source_id="g2",
                subject="finished project",
                state="completed",
                confidence=1.0,
            ),
        ]
    )

    ranked = await ProactiveContinuityService(repo).rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )

    assert [item.source_id for item in ranked] == ["g1"]
    assert "goal_at_risk" in ranked[0].reason_codes


@pytest.mark.asyncio
async def test_behavior_requires_recurrence_and_confidence() -> None:
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="behavior",
                source_id="weak",
                subject="open calendar",
                state="observed",
                confidence=0.9,
                observation_count=1,
            ),
            ContinuityEvidence(
                source_type="behavior",
                source_id="low-confidence",
                subject="review inbox",
                state="recurring",
                confidence=0.4,
                observation_count=8,
            ),
            ContinuityEvidence(
                source_type="behavior",
                source_id="strong",
                subject="review opportunities",
                state="recurring",
                confidence=0.8,
                observation_count=6,
            ),
        ]
    )

    ranked = await ProactiveContinuityService(repo).rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )

    assert [item.source_id for item in ranked] == ["strong"]


@pytest.mark.asyncio
async def test_restricted_domain_requires_current_domain_relevance() -> None:
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="open_loop",
                source_id="finance-loop",
                subject="review stock allocation",
                state="open",
                confidence=0.95,
                domain="finance",
            )
        ]
    )
    service = ProactiveContinuityService(repo)

    generic = await service.rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )
    finance = await service.rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        current_domains=("finance",),
    )

    assert generic == []
    assert [item.source_id for item in finance] == ["finance-loop"]


@pytest.mark.asyncio
async def test_resume_agenda_selects_clear_primary_when_margin_is_large() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="prospective",
                source_id="p1",
                subject="job interview with Ford",
                state="dormant",
                confidence=0.96,
                target_at=now + timedelta(hours=3),
            ),
            ContinuityEvidence(
                source_type="open_loop",
                source_id="o1",
                subject="send the revised estimate",
                state="open",
                confidence=0.95,
            ),
        ]
    )

    agenda = await ProactiveContinuityService(repo).organize(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        now=now,
    )

    assert agenda.primary_candidate_id == agenda.candidates[0].candidate_id
    assert agenda.ambiguous is False
    assert "clear_primary_candidate" in agenda.reason_codes
    assert agenda.execution_authorized is False


@pytest.mark.asyncio
async def test_resume_agenda_refuses_to_guess_between_close_candidates() -> None:
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="open_loop",
                source_id="o1",
                subject="finish the proposal",
                state="open",
                confidence=0.95,
            ),
            ContinuityEvidence(
                source_type="open_loop",
                source_id="o2",
                subject="send the invoice",
                state="open",
                confidence=0.95,
            ),
        ]
    )

    agenda = await ProactiveContinuityService(repo).organize(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )

    assert agenda.primary_candidate_id is None
    assert agenda.ambiguous is True
    assert "candidate_margin_too_small" in agenda.reason_codes


@pytest.mark.asyncio
async def test_resume_agenda_does_not_promote_weak_single_candidate() -> None:
    repo = _Repository(
        [
            ContinuityEvidence(
                source_type="behavior",
                source_id="b1",
                subject="review opportunities",
                state="recurring",
                confidence=0.8,
                observation_count=3,
            )
        ]
    )

    agenda = await ProactiveContinuityService(repo).organize(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )

    assert agenda.primary_candidate_id is None
    assert agenda.ambiguous is True
    assert "top_candidate_below_resume_threshold" in agenda.reason_codes


@pytest.mark.asyncio
async def test_candidate_ids_are_deterministic_for_learning_lineage() -> None:
    evidence = ContinuityEvidence(
        source_type="open_loop",
        source_id="o1",
        subject="finish the draft",
        state="open",
        confidence=0.9,
    )
    repo = _Repository([evidence])
    service = ProactiveContinuityService(repo)

    first = await service.rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )
    second = await service.rank(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
    )

    assert first[0].candidate_id == second[0].candidate_id

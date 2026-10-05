from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.cortex.continuity import (
    ContinuityPlanner,
    ContinuityStateItem,
)


NOW = datetime(2026, 10, 5, 17, 45, tzinfo=timezone.utc)


def _item(
    item_id: str,
    source_type: str,
    description: str,
    *,
    target_at: datetime | None = None,
    domain: str | None = None,
    state: str = "active",
    confidence: float = 0.95,
    metadata: dict[str, object] | None = None,
) -> ContinuityStateItem:
    return ContinuityStateItem(
        item_id=item_id,
        source_type=source_type,
        description=description,
        confidence=confidence,
        lifecycle_state=state,
        source_event_id=f"event-{item_id}",
        target_at=target_at,
        domain=domain,
        metadata=metadata or {},
    )


def test_upcoming_event_outranks_undated_goal() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="What should I do next?",
        now=NOW,
        items=[
            _item("goal", "goal", "Prepare for career growth"),
            _item(
                "interview",
                "prospective",
                "Job interview with Ford",
                target_at=NOW + timedelta(hours=18),
                state="dormant",
            ),
        ],
    )

    assert plan.suggestions[0].source_ref == "interview"
    assert "upcoming_event" in plan.suggestions[0].reason_codes
    assert "near_term" in plan.suggestions[0].reason_codes


def test_current_domain_boosts_relevant_unfinished_work() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="What's left?",
        now=NOW,
        context={"domain": "business"},
        items=[
            _item(
                "client",
                "open_loop",
                "Send the revised estimate",
                domain="business",
                state="open",
            ),
            _item(
                "travel",
                "open_loop",
                "Choose the hotel",
                domain="travel",
                state="open",
            ),
        ],
    )

    assert plan.suggestions[0].source_ref == "client"
    assert "current_domain" in plan.suggestions[0].reason_codes


def test_paused_and_terminal_state_are_not_pushed_as_next_work() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="What next?",
        now=NOW,
        items=[
            _item("paused", "goal", "Paused fitness plan", state="paused"),
            _item("done", "open_loop", "Already done", state="completed"),
        ],
    )

    assert plan.suggestions == ()
    assert plan.reason_codes == ("no_relevant_continuity_state",)


def test_due_item_is_labeled_honestly() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="What's coming up?",
        now=NOW,
        items=[
            _item(
                "due",
                "prospective",
                "Call with supplier",
                target_at=NOW - timedelta(hours=1),
                state="ready",
            )
        ],
    )

    assert "due_or_overdue" in plan.suggestions[0].reason_codes


def test_terse_continuation_requests_trigger_without_substring_false_positives() -> None:
    assert ContinuityPlanner.should_plan("next")
    assert ContinuityPlanner.should_plan("Proceed with the work")
    assert ContinuityPlanner.should_plan("continue fixing this")
    assert not ContinuityPlanner.should_plan("Explain a discontinued product")
    assert not ContinuityPlanner.should_plan("How does Next.js routing work?")


def test_non_continuity_query_does_not_trigger_planning() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="Explain photosynthesis.",
        now=NOW,
        items=[_item("goal", "goal", "Finish biology notes")],
    )

    assert plan.suggestions == ()
    assert plan.reason_codes == ("continuity_not_requested",)


def test_plan_is_non_executable_by_contract() -> None:
    planner = ContinuityPlanner()
    plan = planner.plan(
        query="Continue",
        now=NOW,
        items=[_item("loop", "open_loop", "Finish the report", state="open")],
    )

    payload = plan.to_dict()
    assert payload["execution_authorized"] is False
    assert "commands" not in payload
    assert "tools" not in payload

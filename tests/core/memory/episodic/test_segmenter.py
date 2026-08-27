from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.memory.episodic import (
    EpisodeBoundaryReason,
    EpisodeObservation,
    EventSegmenter,
)


def _obs(
    *,
    minute=0,
    goal="goal-a",
    project="project-a",
    outcome=None,
    correction=False,
    session="session-a",
):
    return EpisodeObservation(
        tenant_id="tenant-a",
        user_id="user-a",
        session_id=session,
        observed_at=datetime(2026, 8, 27, 12, minute, tzinfo=timezone.utc),
        text=f"turn-{minute}",
        goal_key=goal,
        project_key=project,
        outcome_class=outcome,
        correction=correction,
    )


def test_first_observation_starts_episode():
    decision = EventSegmenter().decide(None, _obs())
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.NEW_SESSION
    assert decision.frame.turn_count == 1


def test_same_scope_continues_episode():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs()).frame
    second = segmenter.decide(first, _obs(minute=5))
    assert second.new_episode is False
    assert second.reason is EpisodeBoundaryReason.CONTINUATION
    assert second.frame.episode_group_id == first.episode_group_id
    assert second.frame.turn_count == 2


def test_correction_attaches_to_current_episode():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs()).frame
    decision = segmenter.decide(first, _obs(minute=3, correction=True))
    assert decision.new_episode is False
    assert decision.reason is EpisodeBoundaryReason.CORRECTION_ATTACHED
    assert decision.frame.episode_group_id == first.episode_group_id


def test_project_change_starts_new_episode():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs()).frame
    decision = segmenter.decide(first, _obs(minute=2, project="project-b"))
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.PROJECT_CHANGED
    assert decision.frame.episode_group_id != first.episode_group_id


def test_goal_change_starts_new_episode():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs()).frame
    decision = segmenter.decide(first, _obs(minute=2, goal="goal-b"))
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.GOAL_CHANGED


def test_time_gap_starts_new_episode():
    segmenter = EventSegmenter(time_gap_seconds=60)
    first = segmenter.decide(None, _obs()).frame
    later = EpisodeObservation(
        tenant_id="tenant-a",
        user_id="user-a",
        session_id="session-a",
        observed_at=first.updated_at + timedelta(minutes=2),
        text="later",
        goal_key="goal-a",
        project_key="project-a",
    )
    decision = segmenter.decide(first, later)
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.TIME_GAP


def test_terminal_outcome_closes_episode_for_next_turn():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs(outcome="success")).frame
    decision = segmenter.decide(first, _obs(minute=1))
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.PRIOR_OUTCOME_CLOSED


def test_session_change_is_hard_boundary():
    segmenter = EventSegmenter()
    first = segmenter.decide(None, _obs()).frame
    decision = segmenter.decide(first, _obs(minute=1, session="session-b"))
    assert decision.new_episode is True
    assert decision.reason is EpisodeBoundaryReason.SESSION_CHANGED

from __future__ import annotations

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.services.reward_progress import (
    RewardProgressError,
    RewardProgressService,
)


def _user(user_id: str, tenant_id: str) -> UserData:
    return UserData.from_dict(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "roles": ["user"],
        }
    )


def _execution(
    *,
    trajectory: str,
    tenant_id: str,
    user_id: str,
    metadata: dict | None = None,
) -> dict:
    return {
        "outcome_id": f"out-{trajectory}",
        "trajectory_id": trajectory,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "source": "runtime.execution",
        "status": "success",
        "response_completed": True,
        "persistence_success": True,
        "correlation_id": f"corr-{trajectory}",
        "request_id": f"req-{trajectory}",
        "conversation_id": f"conv-{trajectory}",
        "session_id": f"session-{trajectory}",
        "recorded_at": "2026-10-03T12:00:00+00:00",
        "metadata": dict(metadata or {}),
    }


def test_feedback_is_appended_for_owned_trajectory() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(_execution(trajectory="t1", tenant_id="tenant-a", user_id="user-a"))
    service = RewardProgressService(store=store)

    payload = service.record_feedback(
        _user("user-a", "tenant-a"),
        trajectory_id="t1",
        feedback_type="thumbs_up",
        message_id="assistant-1",
    )

    assert payload["source"] == "user.feedback"
    assert payload["feedback_type"] == "thumbs_up"
    assert payload["message_id"] == "assistant-1"
    assert payload["outcome_store_status"] == "stored"


def test_generic_feedback_keeps_continuity_attribution_weak() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(
        _execution(
            trajectory="t1",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={
                "continuity_candidate_ids": ["next-1", "next-2"],
                "continuity_source_types": ["open_loop", "goal"],
                "continuity_primary_candidate_id": "next-1",
                "continuity_decision_observation_id": "obs-continuity-1",
                "continuity_ambiguous": False,
            },
        )
    )
    service = RewardProgressService(store=store)

    payload = service.record_feedback(
        _user("user-a", "tenant-a"),
        trajectory_id="t1",
        feedback_type="thumbs_up",
    )

    metadata = payload["metadata"]
    assert metadata["continuity_attribution"] == "response_level_weak"
    assert metadata["continuity_attribution_confidence"] == 0.25
    assert metadata["continuity_candidate_ids"] == ["next-1", "next-2"]
    assert "continuity_candidate_id" not in metadata


def test_explicit_candidate_feedback_is_high_confidence() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(
        _execution(
            trajectory="t1",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={
                "continuity_candidate_ids": ["next-1", "next-2"],
                "continuity_source_types": ["open_loop", "goal"],
                "continuity_primary_candidate_id": "next-1",
                "continuity_decision_observation_id": "obs-continuity-1",
                "continuity_ambiguous": False,
            },
        )
    )
    service = RewardProgressService(store=store)

    payload = service.record_feedback(
        _user("user-a", "tenant-a"),
        trajectory_id="t1",
        feedback_type="thumbs_down",
        continuity_candidate_id="next-2",
    )

    metadata = payload["metadata"]
    assert metadata["continuity_attribution"] == "explicit_candidate"
    assert metadata["continuity_attribution_confidence"] == 1.0
    assert metadata["continuity_candidate_id"] == "next-2"
    assert metadata["continuity_source_type"] == "goal"
    assert (
        metadata["continuity_decision_observation_id"]
        == "obs-continuity-1"
    )


def test_feedback_rejects_candidate_not_shown_for_trajectory() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(
        _execution(
            trajectory="t1",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={
                "continuity_candidate_ids": ["next-1"],
                "continuity_source_types": ["open_loop"],
            },
        )
    )
    service = RewardProgressService(store=store)

    with pytest.raises(RewardProgressError, match="not shown"):
        service.record_feedback(
            _user("user-a", "tenant-a"),
            trajectory_id="t1",
            feedback_type="thumbs_up",
            continuity_candidate_id="invented",
        )


def test_feedback_rejects_other_users_trajectory() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(_execution(trajectory="t1", tenant_id="tenant-a", user_id="user-a"))
    service = RewardProgressService(store=store)

    with pytest.raises(RewardProgressError, match="not found"):
        service.record_feedback(
            _user("user-b", "tenant-a"),
            trajectory_id="t1",
            feedback_type="thumbs_down",
        )


def test_feedback_rejects_cross_tenant_trajectory() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome(_execution(trajectory="t1", tenant_id="tenant-a", user_id="user-a"))
    service = RewardProgressService(store=store)

    with pytest.raises(RewardProgressError, match="not found"):
        service.record_feedback(
            _user("user-a", "tenant-b"),
            trajectory_id="t1",
            feedback_type="thumbs_up",
        )

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


def _execution(*, trajectory: str, tenant_id: str, user_id: str) -> dict:
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

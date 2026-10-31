"""Governed history binds observed journal steps to saved assistant digests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.core.runtime import owned_history_projection as projection


DIGEST = "a" * 64


def snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        conversation=SimpleNamespace(id=uuid4(), tenant_id=uuid4(), user_id=uuid4()),
        messages=[
            SimpleNamespace(
                id="assistant-1", role="assistant", content="Saved answer",
                metadata={
                    "source": "chat_runtime",
                    "request_id": "request-owned",
                    "actual_provider": "local",
                    "actual_model": "executed-model",
                    "response_source": "local_inference",
                },
            ),
        ],
    )


def activity(status: str = "completed") -> dict:
    return {
        "seq": 3,
        "event": {
            "type": "CUSTOM", "name": "karen.agent_step",
            "value": {
                "step_id": "step-1", "agent_id": "research",
                "status": status, "event_type": "agent_step_completed",
                "description": "Observed completed step.",
            },
        },
    }


def test_valid_saved_activity_uses_backend_message_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projection, "canonical_message_digest", lambda _: DIGEST)
    result = projection.project_owned_history(
        snapshot(),
        attestations={"assistant-1": ("request-owned", DIGEST)},
        observed_activity={
            "assistant-1": ("request-owned", DIGEST, "run-owned", [activity()]),
        },
    )
    saved = [event for event in result["replayEvents"]
             if event["name"] == "karen.agent_step.v1"]
    assert len(saved) == 1
    assert saved[0]["messageId"] == "assistant-1"
    assert saved[0]["value"]["sequence"] == 3
    assert saved[0]["value"]["run_id"] == "run-owned"
    assert result["replay_only"] is True


@pytest.mark.parametrize("request_id,digest", [
    ("foreign-request", DIGEST),
    ("request-owned", "b" * 64),
])
def test_activity_mismatched_run_attestation_fails_closed(
    monkeypatch: pytest.MonkeyPatch, request_id: str, digest: str,
) -> None:
    monkeypatch.setattr(projection, "canonical_message_digest", lambda _: DIGEST)
    with pytest.raises(
        projection.UnreplayableHistory, match="unattested_observed_activity",
    ):
        projection.project_owned_history(
            snapshot(),
            attestations={"assistant-1": ("request-owned", DIGEST)},
            observed_activity={
                "assistant-1": (request_id, digest, "run-owned", [activity()]),
            },
        )


def test_modified_saved_assistant_message_is_never_restored_as_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projection, "canonical_message_digest", lambda _: "c" * 64)
    with pytest.raises(
        projection.UnreplayableHistory, match="modified_attested_message",
    ):
        projection.project_owned_history(
            snapshot(),
            attestations={"assistant-1": ("request-owned", DIGEST)},
            observed_activity={
                "assistant-1": ("request-owned", DIGEST, "run-owned", [activity()]),
            },
        )



def test_orphaned_observed_activity_fails_closed() -> None:
    """An observed journal entry cannot refer to an absent assistant turn."""
    with pytest.raises(
        projection.UnreplayableHistory, match="orphaned_observed_activity",
    ):
        projection.project_owned_history(
            snapshot(),
            attestations={},
            observed_activity={
                "foreign-assistant": (
                    "request-owned", DIGEST, "run-owned", [activity()],
                ),
            },
        )


def test_activity_bound_to_user_message_fails_closed() -> None:
    """Agent execution belongs to an attested assistant, never a user turn."""
    saved = snapshot()
    saved.messages[0].role = "user"
    with pytest.raises(
        projection.UnreplayableHistory, match="orphaned_observed_activity",
    ):
        projection.project_owned_history(
            saved,
            attestations={},
            observed_activity={
                "assistant-1": (
                    "request-owned", DIGEST, "run-owned", [activity()],
                ),
            },
        )

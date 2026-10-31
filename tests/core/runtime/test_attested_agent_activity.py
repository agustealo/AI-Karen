"""Adversarial tests for the saved observed-agent activity projection contract."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_karen_engine.core.runtime.attested_agent_activity import (
    InvalidAgentActivity,
    project_attested_agent_activity,
)


def observed(seq: int, *, status: object = "completed") -> dict:
    return {
        "seq": seq,
        "event": {
            "type": "CUSTOM",
            "name": "karen.agent_step",
            "value": {
                "step_id": "step-1",
                "agent_id": "research",
                "status": status,
                "event_type": "agent_step_completed",
                "description": "Research completed.",
            },
        },
    }


def project(events: list[dict]) -> list[dict]:
    return project_attested_agent_activity(
        events, message_id="assistant-owned", transport_run_id="run-owned",
    )


def test_preserves_persisted_identity_order_and_actual_status() -> None:
    events = [observed(2, status="running"), observed(7, status="completed")]
    projected = project(events)
    assert [item["value"]["sequence"] for item in projected] == [2, 7]
    assert [item["value"]["status"] for item in projected] == ["running", "completed"]
    assert all(item["messageId"] == "assistant-owned" for item in projected)
    assert all(item["value"]["run_id"] == "run-owned" for item in projected)
    assert all(item["name"] == "karen.agent_step.v1" for item in projected)


@pytest.mark.parametrize("events", [
    [observed(3), observed(3)],
    [observed(8), observed(2)],
    [observed(0)],
    [observed(True)],
    [observed(2049)],
])
def test_rejects_invalid_journal_sequence(events: list[dict]) -> None:
    with pytest.raises(InvalidAgentActivity, match="sequence"):
        project(events)


@pytest.mark.parametrize("status", ["invented", None, 3, {}, [], True])
def test_rejects_unverified_status(status: object) -> None:
    with pytest.raises(InvalidAgentActivity, match="value"):
        project([observed(1, status=status)])


def test_rejects_unknown_event_identity_and_extra_fields() -> None:
    invalid = observed(1)
    invalid["event"]["name"] = "karen.execution_receipt.v1"
    with pytest.raises(InvalidAgentActivity, match="event"):
        project([invalid])
    invalid = observed(1)
    invalid["event"]["value"]["private_token"] = "secret"
    with pytest.raises(InvalidAgentActivity, match="fields"):
        project([invalid])


def test_rejects_oversized_activity_and_bad_run_binding() -> None:
    with pytest.raises(InvalidAgentActivity, match="envelope"):
        project([observed(seq) for seq in range(1, 102)])
    with pytest.raises(InvalidAgentActivity, match="envelope"):
        project_attested_agent_activity(
            [], message_id=" ", transport_run_id="run-owned",
        )
    with pytest.raises(InvalidAgentActivity, match="envelope"):
        project_attested_agent_activity(
            [], message_id="assistant-owned", transport_run_id="",
        )


@pytest.mark.parametrize("invalid_run_id", [
    "run with spaces", "run/foreign", "../run", "run\\nother",
    "éxternal", "x" * 101,
])
def test_rejects_noncanonical_transport_run_id(invalid_run_id: str) -> None:
    with pytest.raises(InvalidAgentActivity, match="envelope"):
        project_attested_agent_activity(
            [observed(1)],
            message_id="assistant-owned",
            transport_run_id=invalid_run_id,
        )


def test_rejects_raw_reasoning_length() -> None:
    invalid = deepcopy(observed(1))
    invalid["event"]["value"]["description"] = "private" * 500
    with pytest.raises(InvalidAgentActivity, match="value"):
        project([invalid])

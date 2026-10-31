"""Validate observed agent-step journal projections for governed history.

This is a pure, non-executing presentation contract. The caller MUST first
authorize the run, bind it to an atomically completed assistant message and
verify that message's saved digest against the existing run ledger.
This module never creates an attestation or reads an alternate store.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_ALLOWED_STATUSES = frozenset({"running", "completed", "failed", "cancelled", "skipped"})
_MAX_EVENTS_PER_MESSAGE = 100
_MAX_FIELD = 200
_MAX_DESCRIPTION = 2000


class InvalidAgentActivity(ValueError):
    """Observed journal activity cannot be represented safely."""


def project_attested_agent_activity(
    events: Sequence[Mapping[str, Any]],
    *,
    message_id: str,
    transport_run_id: str,
) -> list[dict[str, Any]]:
    """Project a previously authorized run's ordered CUSTOM step events.

    The caller supplies journal records with seq and event fields.
    Sequence numbers are increasing but need not be contiguous, because
    non-step AG-UI events also occupy positions in the same journal.
    """
    if (
        not isinstance(message_id, str) or not message_id.strip()
        or len(message_id) > _MAX_FIELD
        or not isinstance(transport_run_id, str)
        or not transport_run_id
        or len(transport_run_id) > 100
        or not isinstance(events, (list, tuple))
        or len(events) > _MAX_EVENTS_PER_MESSAGE
    ):
        raise InvalidAgentActivity("invalid_agent_activity_envelope")

    result: list[dict[str, Any]] = []
    prior_seq = 0
    for row in events:
        if not isinstance(row, Mapping):
            raise InvalidAgentActivity("invalid_agent_activity_record")
        seq = row.get("seq")
        event = row.get("event")
        if type(seq) is not int or seq <= prior_seq or seq > 2048:
            raise InvalidAgentActivity("invalid_agent_activity_sequence")
        prior_seq = seq
        if not isinstance(event, Mapping) or set(event) != {"type", "name", "value"}:
            raise InvalidAgentActivity("invalid_agent_activity_event")
        if event.get("type") != "CUSTOM" or event.get("name") != "karen.agent_step":
            raise InvalidAgentActivity("invalid_agent_activity_event")
        value = event.get("value")
        if not isinstance(value, Mapping):
            raise InvalidAgentActivity("invalid_agent_activity_value")
        if set(value) - {"step_id", "event_type", "status", "agent_id", "description"}:
            raise InvalidAgentActivity("invalid_agent_activity_fields")
        step_id = value.get("step_id")
        agent_id = value.get("agent_id")
        status = value.get("status")
        event_type = value.get("event_type")
        description = value.get("description")
        if (
            not isinstance(step_id, str) or not step_id.strip()
            or len(step_id) > 128
            or not isinstance(agent_id, str) or not agent_id.strip()
            or len(agent_id) > 128
            or status not in _ALLOWED_STATUSES
            or not isinstance(event_type, str) or len(event_type) > 64
            or not isinstance(description, str)
            or len(description) > _MAX_DESCRIPTION
        ):
            raise InvalidAgentActivity("invalid_agent_activity_value")
        result.append({
            "type": "CUSTOM",
            "name": "karen.agent_step.v1",
            "messageId": message_id,
            "value": {
                "step_id": step_id,
                "agent_id": agent_id,
                "status": status,
                "event_type": event_type,
                "description": description,
                "run_id": transport_run_id,
                "sequence": seq,
            },
        })
    return result

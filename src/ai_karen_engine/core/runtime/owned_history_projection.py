"""CK-07D: bounded, attested projection of canonical saved conversation history.

This is read-only presentation adaptation, not a message store or executor.
Only backend-attested, atomically completed run/message pairs may restore
runtime-specific rich data. Unsupported content fails the entire projection.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from typing import Any

from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection
from ai_karen_engine.core.runtime.attested_agent_activity import (
    InvalidAgentActivity, project_attested_agent_activity,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk
from ai_karen_engine.core.runtime.conversation_runtime_gateway import ConversationSnapshot
from ai_karen_engine.core.runtime.presentation_contract import validate_presentation
from ai_karen_engine.services.database.repositories.conversation_repository import canonical_message_digest

_MAX_MESSAGES = 500
_MAX_BYTES = 2 * 1024 * 1024
_MAX_TEXT = 65536
_MAX_PRESENTATIONS = 6

_UNSUPPORTED_RICH = frozenset({
    "structured_content", "actions", "citations", "sources",
    "attachments", "artifacts", "function_call", "function_response",
    "tool_activity", "tool_calls", "tool_results", "agent_steps",
    "execution_receipt", "presentation", "presentation_payload",
    "karen.presentation.v1",
})
_RUNTIME_RECEIPT = frozenset({
    "actual_provider", "actual_model", "response_source",
    "requested_provider", "requested_model", "runtime_engine",
    "fallback_level", "degradation_reason", "degraded_mode",
    "output_truncated", "cortex_intent",
})


class UnreplayableHistory(ValueError):
    """Canonical history cannot be restored accurately under this contract."""


def _carries_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def project_owned_history(
    snapshot: ConversationSnapshot,
    *,
    attestations: Mapping[str, tuple[str, str]],
    observed_activity: Mapping[str, tuple[str, str, str, list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    """Build complete text snapshot plus vetted CUSTOM events or fail closed."""
    records = snapshot.messages
    if len(records) > _MAX_MESSAGES:
        raise UnreplayableHistory("history_message_limit")
    thread_id = str(snapshot.conversation.id)
    messages: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    seen_message_ids: set[str] = set()

    for message in records:
        role = str(message.role)
        identifier = str(message.id)
        content = message.content
        if (
            role not in {"user", "assistant"}
            or not identifier or not identifier.strip() or len(identifier) > 200
            or identifier in seen_message_ids
            or not isinstance(content, str)
            or len(content) > _MAX_TEXT
        ):
            raise UnreplayableHistory("invalid_canonical_message")
        seen_message_ids.add(identifier)
        metadata = message.metadata
        if not isinstance(metadata, Mapping):
            raise UnreplayableHistory("invalid_message_metadata")
        if any(_carries_value(metadata.get(key)) for key in _UNSUPPORTED_RICH):
            raise UnreplayableHistory("unsupported_rich_history")
        if metadata.get("presentation_replay_incomplete") is True:
            raise UnreplayableHistory("incomplete_presentation_capture")

        observed = (observed_activity or {}).get(identifier)
        rich = (
            observed is not None
            any(_carries_value(metadata.get(key)) for key in _RUNTIME_RECEIPT)
            or _carries_value(metadata.get("verified_presentations_v1"))
        )
        if rich:
            # Metadata labels alone are NOT attestation. Only exact message
            # identities committed with a completed ledger run qualify.
            attestation = attestations.get(identifier)
            if (
                role != "assistant"
                or str(metadata.get("source")) != "chat_runtime"
                or not isinstance(metadata.get("request_id"), str)
                or not isinstance(attestation, tuple)
                or len(attestation) != 2
                or attestation[0] != metadata["request_id"]
                or not isinstance(attestation[1], str)
            ):
                raise UnreplayableHistory("unattested_runtime_metadata")
            try:
                digest = canonical_message_digest(message)
            except (TypeError, ValueError, OverflowError) as exc:
                raise UnreplayableHistory("unserializable_attested_message") from exc
            if not hmac.compare_digest(digest, attestation[1]):
                raise UnreplayableHistory("modified_attested_message")
            if observed is not None:
                if (
                    len(observed) != 4
                    or observed[0] != attestation[0]
                    or not hmac.compare_digest(observed[1], attestation[1])
                ):
                    raise UnreplayableHistory("unattested_observed_activity")
                try:
                    events.extend(project_attested_agent_activity(
                        observed[3], message_id=identifier,
                        transport_run_id=observed[2],
                    ))
                except InvalidAgentActivity as exc:
                    raise UnreplayableHistory("invalid_attested_agent_activity") from exc
            projector = AGUIEventProjection(
                thread_id=thread_id,
                run_id="restored_" + identifier.replace("-", "_"),
            )
            projector.begin()
            verified = metadata.get("verified_presentations_v1")
            if verified is not None:
                if (
                    not isinstance(verified, list)
                    or not 1 <= len(verified) <= _MAX_PRESENTATIONS
                ):
                    raise UnreplayableHistory("invalid_persisted_presentation")
                for candidate in verified:
                    valid = validate_presentation(candidate)
                    if valid is None or valid != candidate:
                        raise UnreplayableHistory("invalid_persisted_presentation")
                    for event in projector.project(ChatStreamChunk(
                        type="presentation",
                        content="",
                        metadata={"presentation_verified": True, "presentation": valid},
                    )):
                        if event.get("type") != "CUSTOM" or event.get("name") != "karen.presentation.v1":
                            raise UnreplayableHistory("invalid_presentation_projection")
                        events.append({**event, "messageId": identifier})
            for event in projector.project(ChatStreamChunk(
                type="complete", content="", metadata=dict(metadata),
            )):
                if event.get("type") == "CUSTOM":
                    if event.get("name") not in {
                        "karen.execution_receipt.v1", "karen.response_integrity.v1",
                    }:
                        raise UnreplayableHistory("unexpected_replay_event")
                    events.append({**event, "messageId": identifier})
                elif event.get("type") not in {"RUN_FINISHED"}:
                    raise UnreplayableHistory("unexpected_replay_event")
        messages.append({"id": identifier, "role": role, "content": content})

    result = {
        "schema_version": 1,
        "threadId": thread_id,
        "owner_user_id": str(snapshot.conversation.user_id),
        "owner_tenant_id": str(snapshot.conversation.tenant_id),
        "messages": messages,
        "replayEvents": events,
        "response_source": "persisted_history",
        "replay_only": True,
    }
    try:
        length = len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnreplayableHistory("unserializable_history") from exc
    if length > _MAX_BYTES:
        raise UnreplayableHistory("history_byte_limit")
    return result

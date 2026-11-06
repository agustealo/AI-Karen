"""CK-07D: bounded, attested projection of canonical saved conversation history.

This is read-only presentation adaptation, not a message store or executor.
Only backend-attested, atomically completed run/message pairs may restore
runtime-specific rich data. Unsupported content fails complete rich replay.
Explicit text continuation is a separate, attestation-checked projection that
never fabricates rich events or permits model execution by itself.
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
    "actions", "citations", "sources",
    "attachments", "artifacts", "function_call", "function_response",
    "tool_activity", "tool_calls", "tool_results", "agent_steps",
    "execution_receipt", "presentation", "presentation_payload",
    "karen.presentation.v1",
})
# DirectCapabilityResult.normalized_metadata writes observation/support fields
# alongside the approved presentation. They are not independent UI parts.
# Only this canonical, bounded key set can accompany an identical saved
# presentation; arbitrary structured payloads remain unreplayable.
_VERIFIED_PRESENTATION_CONTEXT_KEYS = frozenset({
    "presentation", "query", "mode", "status", "value", "formatted",
    "time", "date", "timezone", "resolved_timezone", "label",
    "extractedData", "insights", "required_capability", "target",
    "next_action", "provider", "search_providers", "crawl_provider",
    "timer_receipt",
})

_RUNTIME_RECEIPT = frozenset({
    "actual_provider", "actual_model", "response_source",
    "requested_provider", "requested_model", "runtime_engine",
    "fallback_level", "degradation_reason", "degraded_mode",
    "output_truncated", "cortex_intent",
})


# Stable, non-sensitive failure classes. Message data, metadata values,
# account identifiers and SQL errors must never become diagnostic reason codes.
_REPLAY_REASON_CODES = frozenset({
    "history_message_limit",
    "orphaned_observed_activity",
    "invalid_canonical_message",
    "invalid_message_metadata",
    "unsupported_rich_history",
    "incomplete_presentation_capture",
    "unattested_runtime_metadata",
    "unserializable_attested_message",
    "modified_attested_message",
    "unattested_observed_activity",
    "invalid_attested_agent_activity",
    "invalid_persisted_presentation",
    "invalid_presentation_projection",
    "unexpected_replay_event",
    "unserializable_history",
    "history_byte_limit",
})


class UnreplayableHistory(ValueError):
    """Canonical history cannot be restored accurately under this contract."""

    @property
    def safe_reason_code(self) -> str:
        """Diagnostic classification only; never forward exception text."""
        reason = self.args[0] if len(self.args) == 1 else None
        return reason if isinstance(reason, str) and reason in _REPLAY_REASON_CODES else "unknown"


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
    text_continuation: bool = False,
) -> dict[str, Any]:
    """Project trusted history. Explicit text mode drops every rich event.

    Authorization is already checked by ConversationRuntimeGateway. Rich
    metadata must still be bound to a completed, exact-digest run. The caller
    must require a separate explicit user action before mounting text mode.
    """
    records = snapshot.messages
    if len(records) > _MAX_MESSAGES:
        raise UnreplayableHistory("history_message_limit")
    thread_id = str(snapshot.conversation.id)
    if observed_activity:
        eligible_ids = {
            str(message.id) for message in records
            if str(message.role) == "assistant"
        }
        if any(identifier not in eligible_ids for identifier in observed_activity):
            raise UnreplayableHistory("orphaned_observed_activity")
    messages: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    seen_message_ids: set[str] = set()
    omitted_rich_message_count = 0

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
        has_unknown_rich = any(
            _carries_value(metadata.get(key)) for key in _UNSUPPORTED_RICH
        )
        if has_unknown_rich and not text_continuation:
            raise UnreplayableHistory("unsupported_rich_history")

        # The direct-capability stream persists its *same* approved surface
        # twice: under structured_content for existing consumers and under
        # verified_presentations_v1 for the durable AG-UI replay projection.
        # Reject arbitrary structured data, but never reject a proven first
        # response simply because it has this duplicate canonical envelope.
        # Runtime attestation and the digest check below still govern both.
        structured = metadata.get("structured_content")
        if _carries_value(structured) and not text_continuation:
            captured = metadata.get("verified_presentations_v1")
            if (
                not isinstance(structured, Mapping)
                or not set(structured).issubset(_VERIFIED_PRESENTATION_CONTEXT_KEYS)
                or not isinstance(captured, list)
                or len(captured) != 1
                or "presentation" not in structured
                or structured["presentation"] != captured[0]
            ):
                raise UnreplayableHistory("unsupported_rich_history")
        incomplete_presentation = metadata.get("presentation_replay_incomplete") is True
        if incomplete_presentation and not text_continuation:
            raise UnreplayableHistory("incomplete_presentation_capture")

        observed = (observed_activity or {}).get(identifier)
        rich = (
            observed is not None
            or any(_carries_value(metadata.get(key)) for key in _RUNTIME_RECEIPT)
            or _carries_value(metadata.get("verified_presentations_v1"))
            or (
                text_continuation and (
                    has_unknown_rich
                    or _carries_value(structured)
                    or incomplete_presentation
                )
            )
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
                    validated_activity = project_attested_agent_activity(
                        observed[3], message_id=identifier,
                        transport_run_id=observed[2],
                    )
                except InvalidAgentActivity as exc:
                    raise UnreplayableHistory("invalid_attested_agent_activity") from exc
                if not text_continuation:
                    events.extend(validated_activity)
            if text_continuation:
                # Exact canonical content may be viewed and continued, but
                # rich metadata, actions and receipts are never rehydrated.
                # SDK state changes here do not invoke a model or tools.
                omitted_rich_message_count += 1
                messages.append({"id": identifier, "role": role, "content": content})
                continue
            # Rebuild events from a previously completed run. Its attested
            # request identity is stable even when older saved messages lack
            # correlation_id. This identifier is only required to satisfy
            # ChatStreamChunk's canonical typing; AGUIEventProjection does
            # not publish it as a claim about the original tracing ID.
            replay_trace_id = attestation[0]
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
                        correlation_id=replay_trace_id,
                        metadata={"presentation_verified": True, "presentation": valid},
                    )):
                        if event.get("type") != "CUSTOM" or event.get("name") != "karen.presentation.v1":
                            raise UnreplayableHistory("invalid_presentation_projection")
                        events.append({**event, "messageId": identifier})
            for event in projector.project(ChatStreamChunk(
                type="complete", content="",
                correlation_id=replay_trace_id,
                metadata=dict(metadata),
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
    if text_continuation:
        result.update({
            "text_only": True,
            "continuation_authorized": True,
            "omitted_rich_message_count": omitted_rich_message_count,
        })
    try:
        length = len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnreplayableHistory("unserializable_history") from exc
    if length > _MAX_BYTES:
        raise UnreplayableHistory("history_byte_limit")
    return result

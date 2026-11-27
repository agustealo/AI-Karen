"""CK-07D: bounded, attested projection of canonical saved conversation history.

This is read-only presentation adaptation, not a message store or executor.
Only backend-attested, atomically completed run/message pairs may restore
runtime-specific rich data. Unsupported content fails complete rich replay.
Explicit text continuation is a separate, attestation-checked projection that
never fabricates rich events or permits model execution by itself.
"""

from __future__ import annotations

import hashlib
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
from ai_karen_engine.core.runtime.presentation_contract import (
    contains_revocable_code_artifact,
    is_public_source_url,
    validate_presentation,
)
from ai_karen_engine.core.runtime.plugin_management_contract import (
    validate_plugin_management_preflight,
)
from ai_karen_engine.services.database.repositories.conversation_repository import canonical_message_digest
from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_validator import ResponseValidator

_MAX_MESSAGES = 500
_MAX_BYTES = 2 * 1024 * 1024
_MAX_TEXT = 65536
_MAX_PRESENTATIONS = 6

_UNSUPPORTED_RICH = frozenset({
    "actions",
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


def _is_degraded_direct_search_context(metadata: Mapping[str, Any]) -> bool:
    """Allow withheld search metadata from a degraded direct-capability turn.

    When live crawl degrades after search discovery, ChatRuntime intentionally
    withholds verified_presentations_v1 while persisting the canonical text
    answer, bounded search diagnostics, and source receipts. This helper grants
    no presentation or replay authority: raw sources never reach the UI and
    project_owned_history still requires exact completed-run digest attestation.
    """
    structured = metadata.get("structured_content")
    return (
        metadata.get("source") == "chat_runtime"
        and isinstance(metadata.get("request_id"), str)
        and metadata.get("response_source") == "tool"
        and metadata.get("runtime_engine") == "direct_capability"
        and metadata.get("degraded_mode") is True
        and metadata.get("verified_presentations_v1") is None
        and isinstance(structured, Mapping)
        and set(structured).issubset(_VERIFIED_PRESENTATION_CONTEXT_KEYS - {"presentation"})
        and structured.get("status") == "ok"
        and isinstance(structured.get("mode"), str)
        and isinstance(structured.get("query"), str)
    )


def _verified_document_receipt(metadata: Mapping[str, Any]) -> bool:
    """Recognize the generated-text producer's duplicate creation receipt.

    The canonical presentation validator owns the receipt schema. Both
    persisted copies and the captured live presentation must describe the
    same immutable receipt. This grants no current artifact access; the
    ordinary completed-run attestation and authorized artifact read remain
    mandatory at their respective boundaries.
    """
    artifacts = metadata.get("artifacts")
    structured = metadata.get("structured_content")
    captured = metadata.get("verified_presentations_v1")
    if (
        not isinstance(artifacts, list) or len(artifacts) != 1
        or not isinstance(structured, Mapping) or set(structured) != {"presentation"}
        or not isinstance(captured, list) or len(captured) != 1
    ):
        return False
    part = validate_presentation(captured[0])
    if (
        part is None or part != captured[0]
        or part["component_type"] != "document.artifact"
    ):
        return False
    # Validate each copy independently: Python equality alone accepts
    # boolean/integer and integer/float substitutions for size_bytes.
    structured_part = validate_presentation(structured["presentation"])
    receipt_part = validate_presentation({**part, "data": artifacts[0]})
    return (
        structured_part is not None
        and structured_part == structured["presentation"] == part
        and receipt_part is not None
        and receipt_part == part
    )


def _verified_citation_urls(metadata: Mapping[str, Any], content: str) -> list[str] | None:
    """Check exact historical URL provenance; never re-fetch or grant access."""
    receipt = metadata.get("verified_citation_receipt_v1")
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"schema_version", "request_id", "answer_sha256",
                            "source_kind", "source_id", "urls"}
        or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
        or metadata.get("response_source") != "grounded_search_model"
        or metadata.get("answer_composition_status") != "grounded_model"
        or metadata.get("degraded_mode") is not False
        or not isinstance(receipt["request_id"], str) or not receipt["request_id"]
        or receipt["request_id"] != metadata.get("request_id")
        or receipt["source_kind"] not in ("tool", "plugin")
        or not isinstance(receipt["source_id"], str)
        or not 1 <= len(receipt["source_id"]) <= 128
    ):
        return None
    try:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    except UnicodeError:
        return None
    if receipt["answer_sha256"] != digest:
        return None
    urls = receipt["urls"]
    if (
        not isinstance(urls, list) or not 1 <= len(urls) <= 50
        or any(not is_public_source_url(url) for url in urls)
        or len(set(urls)) != len(urls)
    ):
        return None
    attempts = metadata.get("provider_attempts")
    if not isinstance(attempts, list) or len(attempts) > 100 or not any(
        isinstance(attempt, Mapping)
        and attempt.get("type") == receipt["source_kind"]
        and attempt.get("id") == receipt["source_id"]
        and attempt.get("status") == "success"
        for attempt in attempts
    ):
        return None
    sources = metadata.get("sources")
    if not isinstance(sources, list) or len(sources) > 100:
        return None
    # Only top-level fetched URL identities may be used. Nested provider
    # fields, discovery links and raw citations cannot manufacture evidence.
    evidence = [
        {"url": row["url"], "evidence_level": "fetched_page"}
        for row in sources
        if isinstance(row, Mapping) and row.get("evidence_level") == "fetched_page"
        and is_public_source_url(row.get("url"))
    ]
    verdict = ResponseValidator().validate(content, ResponseContract(
        purpose="tool_synthesis", requires_live_data=True,
        tool_results=[{"sources": evidence}],
    ))
    if not verdict.valid or verdict.verified_citation_urls != tuple(urls):
        return None
    return list(urls)


def _verified_source_context(
    metadata: Mapping[str, Any], *, verified_citations: bool = False,
) -> bool:
    """Allow *withheld* provider source metadata only with an attested UI part.

    This function grants no execution/replay authority. The completed-run
    digest is still required in project_owned_history and raw source payloads
    never reach the CopilotKit event projection.
    """
    sources = metadata.get("sources")
    citations = metadata.get("citations")
    if not _carries_value(sources) and not _carries_value(citations):
        return True

    if sources is not None and not isinstance(sources, list):
        return False
    if citations is not None and not isinstance(citations, list):
        return False
    source_rows = sources or []
    citation_rows = citations or []
    if len(source_rows) > 100 or len(citation_rows) > 100:
        return False
    if any(
        not isinstance(row, Mapping)
        or not isinstance(row.get("url"), str)
        or not 1 <= len(row["url"]) <= 1200
        for row in source_rows + citation_rows
    ):
        return False

    if _is_degraded_direct_search_context(metadata):
        return True

    structured = metadata.get("structured_content")
    captured = metadata.get("verified_presentations_v1")
    if verified_citations and captured is None and (
        not _carries_value(structured) or (
            isinstance(structured, Mapping)
            and set(structured).issubset(_VERIFIED_PRESENTATION_CONTEXT_KEYS - {"presentation"})
        )
    ):
        return True
    if (
        not isinstance(structured, Mapping)
        or not isinstance(captured, list)
        or len(captured) != 1
        or structured.get("presentation") != captured[0]
    ):
        return False
    part = validate_presentation(captured[0])
    if part is None or part != captured[0]:
        return False
    # The runtime may arrange its already verified observations in a bounded
    # composition. Only source-backed search/weather children are supported
    # here; do not treat a layout plan as independent evidence authority.
    parts = (
        part["data"]["items"]
        if part["component_type"] == "surface.composition"
        else [part]
    )
    if any(child["component_type"] not in {
        "search.results", "weather.observation", "weather.comparison",
    } for child in parts):
        return False
    if len({child["presentation_id"] for child in parts}) != len(parts):
        return False
    # A source/citation-bearing capability must carry the original completed
    # request receipt; unpaired metadata from historical/legacy messages
    # cannot be silently admitted as if it were verified.
    if metadata.get("source") != "chat_runtime" or not isinstance(metadata.get("request_id"), str):
        return False
    request_id = metadata["request_id"]
    if not request_id:
        return False
    prefix = request_id + ":"
    references = {child["evidence_ref"] for child in parts}
    if any(not ref.startswith(prefix) or len(ref) <= len(prefix) for ref in references):
        return False
    expected = (
        next(iter(references)) if len(references) == 1
        else f"bundle:{request_id}"
    )
    if part["evidence_ref"] != expected:
        return False

    for child in parts:
        if child["component_type"] != "search.results":
            continue
        # Every displayed search result, including nested source cards, must
        # match saved source receipts. Raw citations remain withheld.
        for displayed in child["data"]["results"]:
            if not any(
                row["url"] == displayed["url"]
                and str(row.get("snippet") or row.get("content") or "").strip()
                    == displayed["snippet"]
                and ("title" not in displayed or row.get("title") == displayed["title"])
                and (
                    "published_at" not in displayed
                    or row.get("published_at") == displayed["published_at"]
                )
                for row in source_rows
            ):
                return False
    # Weather observations have independent source measurements and optional
    # citation links; the original weather contract and completed-run digest
    # determine validity. Never imply that a citation itself is a measurement.
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
            _carries_value(metadata.get(key))
            and not (key == "artifacts" and _verified_document_receipt(metadata))
            for key in _UNSUPPORTED_RICH
        )
        has_source_context = any(
            _carries_value(metadata.get(key)) for key in ("sources", "citations")
        )
        has_citation_receipt = "verified_citation_receipt_v1" in metadata
        citation_urls = (
            _verified_citation_urls(metadata, content)
            if has_citation_receipt and not text_continuation else None
        )
        if has_citation_receipt and not text_continuation and citation_urls is None:
            raise UnreplayableHistory("unsupported_rich_history")
        if has_unknown_rich and not text_continuation:
            raise UnreplayableHistory("unsupported_rich_history")
        # Raw source and citation records may accompany a *fully attested*
        # saved surface but cannot independently authorize new UI claims.
        # In explicit text-only continuation, these are withheld; the exact
        # completed-run digest remains necessary for the affected message.
        if not text_continuation and not _verified_source_context(
            metadata, verified_citations=citation_urls is not None,
        ):
            raise UnreplayableHistory("unsupported_rich_history")

        # The direct-capability stream persists its *same* approved surface
        # twice: under structured_content for existing consumers and under
        # verified_presentations_v1 for the durable AG-UI replay projection.
        # Reject arbitrary structured data, but never reject a proven first
        # response simply because it has this duplicate canonical envelope.
        # Runtime attestation and the digest check below still govern both.
        structured = metadata.get("structured_content")
        if _carries_value(structured) and not text_continuation:
            management = (
                validate_plugin_management_preflight(
                    structured.get("plugin_management_preflight")
                ) if isinstance(structured, Mapping) else None
            )
            if management is not None:
                # A separate, immutable, bounded status is allowed only for a
                # confirmed plugin.inspect response. It cannot import catalog
                # candidates, tool arguments, secrets or a mutation receipt.
                if (
                    set(structured) != {
                        "status", "plugin_management_preflight",
                        "requested_action_executed", "next_action",
                    }
                    or structured["status"] != "found"
                    or structured["requested_action_executed"] is not False
                    or structured["next_action"] != management["next_action"]
                    or metadata.get("response_source") != "plugin_catalog"
                    or metadata.get("capability_executor") != "plugin.inspect"
                    or metadata.get("verified_presentations_v1") is not None
                ):
                    raise UnreplayableHistory("unsupported_rich_history")
            elif (
                metadata.get("response_source") == "runtime_registry_observation"
                and metadata.get("runtime_engine") == "direct_capability"
                and metadata.get("actual_provider") is None
                and metadata.get("actual_model") is None
                and metadata.get("verified_presentations_v1") is None
                and isinstance(structured, Mapping)
            ):
                # Runtime inspection is a text observation with structured snapshot
                # metadata. Reject arbitrary payloads, unobserved statuses, or
                # foreign observation origins.
                if (
                    structured.get("status") != "observed"
                    or structured.get("required_capability") != "runtime.inspect"
                    or not set(structured).issubset({
                        "status", "required_capability", "capability_snapshot",
                    })
                ):
                    raise UnreplayableHistory("unsupported_rich_history")
                snapshot_val = structured.get("capability_snapshot")
                if snapshot_val is not None:
                    if (
                        not isinstance(snapshot_val, Mapping)
                        or snapshot_val.get("source") != "authenticated_runtime_observation"
                    ):
                        raise UnreplayableHistory("unsupported_rich_history")
            elif (
                citation_urls is not None
                and metadata.get("verified_presentations_v1") is None
                and isinstance(structured, Mapping)
                and set(structured).issubset(_VERIFIED_PRESENTATION_CONTEXT_KEYS - {"presentation"})
            ):
                # A validated citation receipt supports text plus links, not
                # a fabricated presentation from withheld search metadata.
                pass
            elif _is_degraded_direct_search_context(metadata):
                # Bounded degraded search diagnostics; raw sources remain
                # withheld and exact completed-run attestation still runs below.
                pass
            else:
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
            or has_citation_receipt
            or any(_carries_value(metadata.get(key)) for key in _RUNTIME_RECEIPT)
            or _carries_value(metadata.get("verified_presentations_v1"))
            or (
                text_continuation and (
                    has_unknown_rich
                    or has_source_context
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
            recorded_correlation = metadata.get("correlation_id")
            replay_trace_id = (
                recorded_correlation
                if isinstance(recorded_correlation, str)
                and 1 <= len(recorded_correlation) <= 160
                else attestation[0]
            )
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
                    # Attested history can outlive code-source authorization.
                    # Never restore revocable code from legacy saved metadata.
                    if contains_revocable_code_artifact(valid):
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
            if citation_urls is not None:
                events.append({
                    "type": "CUSTOM", "name": "karen.verified_citations.v1",
                    "messageId": identifier, "value": {"urls": citation_urls},
                })
            for event in projector.project(ChatStreamChunk(
                type="complete", content="",
                correlation_id=replay_trace_id,
                request_id=attestation[0],
                metadata=dict(metadata),
            )):
                if event.get("type") == "CUSTOM":
                    if event.get("name") not in {
                        "karen.execution_receipt.v1", "karen.response_integrity.v1",
                        "karen.plugin_management_preflight.v1",
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

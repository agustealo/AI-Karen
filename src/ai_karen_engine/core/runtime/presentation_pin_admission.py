"""KUI-002D: fail-closed admission of a reference to a saved presentation.

This module is a read-only authorization gate, NOT a pin store or route.
The caller must fetch the snapshot with ConversationRuntimeGateway's owned
authorization and supply attestations from the canonical completed-run ledger.
Never derive an attestation from untrusted request content. No client-selected
tenant/user or model data can authorize a pin.

Source references become eligible only when the existing owned-history
projection admits the exact presentation from the saved assistant turn.
Deletion, RBAC revocation, digest drift and unsupported replay must deny a pin
on every future read, even after a pin-record service is added.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.core.runtime.owned_history_projection import (
    UnreplayableHistory,
    project_owned_history,
)


class PinSourceUnavailable(ValueError):
    """Requested saved presentation is not provably owned and attested."""


@dataclass(frozen=True, slots=True)
class PresentationPinReference:
    conversation_id: str
    assistant_message_id: str
    presentation_id: str
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class AdmittedPresentationPin:
    reference: PresentationPinReference
    component_type: str
    schema_version: int


def _valid_id(value: object, *, length: int = 200) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= length


def admit_presentation_pin_reference(
    *,
    snapshot: ConversationSnapshot,
    authenticated_tenant_id: str,
    authenticated_user_id: str,
    reference: PresentationPinReference,
    attestations: Mapping[str, tuple[str, str]],
) -> AdmittedPresentationPin:
    """Prove an exact saved assistant presentation is eligible for pinning.

    Authorization contract: snapshot MUST have been returned by an authorized
    ConversationRuntimeGateway read. Supplied principal identities must come
    only from the authenticated server context. Attestations MUST be retrieved
    from the completed-run ledger, never fabricated from saved message digests.

    The only returned evidence is a bounded validated reference and its
    allowlisted type; no private presentation content is copied or stored.
    All denials use one non-enumerating error category.
    """
    denied = PinSourceUnavailable("Saved presentation unavailable")
    try:
        if (
            not _valid_id(authenticated_tenant_id)
            or not _valid_id(authenticated_user_id)
            or not isinstance(reference, PresentationPinReference)
            or not _valid_id(reference.conversation_id)
            or not _valid_id(reference.assistant_message_id)
            or not _valid_id(reference.presentation_id, length=160)
            or not _valid_id(reference.evidence_ref, length=160)
            or not hmac.compare_digest(
                str(snapshot.conversation.tenant_id), authenticated_tenant_id
            )
            or not hmac.compare_digest(
                str(snapshot.conversation.user_id), authenticated_user_id
            )
            or not hmac.compare_digest(
                str(snapshot.conversation.id), reference.conversation_id
            )
        ):
            raise denied

        # The canonical projector itself validates message order and identity,
        # complete-run digests and replayable rich schemas. An unverified
        # presentation must never pass simply because its ID is plausible.
        projection = project_owned_history(
            snapshot, attestations=attestations, text_continuation=False
        )
        if (
            projection.get("threadId") != reference.conversation_id
            or projection.get("owner_user_id") != authenticated_user_id
            or projection.get("owner_tenant_id") != authenticated_tenant_id
            or projection.get("replay_only") is not True
        ):
            raise denied

        matches: list[Mapping[str, Any]] = []
        for event in projection["replayEvents"]:
            if (
                event.get("type") != "CUSTOM"
                or event.get("name") != "karen.presentation.v1"
                or event.get("messageId") != reference.assistant_message_id
            ):
                continue
            envelope = event.get("value")
            if not isinstance(envelope, Mapping):
                raise denied
            if (
                envelope.get("presentation_id") == reference.presentation_id
                and envelope.get("evidence_ref") == reference.evidence_ref
            ):
                matches.append(envelope)
        if len(matches) != 1:
            raise denied
        verified = matches[0]
        component_type = verified.get("component_type")
        if not _valid_id(component_type, length=80):
            raise denied
        if verified.get("schema_version") != 1:
            raise denied
        return AdmittedPresentationPin(
            reference=reference,
            component_type=component_type,
            schema_version=1,
        )
    except (UnreplayableHistory, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise PinSourceUnavailable("Saved presentation unavailable") from exc

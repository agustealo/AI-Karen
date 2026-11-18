"""KUI-002D2: reauthorized readback of durable presentation pin references.

No raw reference is a grant. Each read uses the canonical owned conversation
gateway and completed-run attestation ledger before returning any entry.
Stale, deleted, revoked, malformed or unverifiable references stay hidden.

This service does NOT expose HTTP routes, render saved cards, or authorize
writes. The future route must authenticate the context before delegating here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    ConversationSnapshot,
    get_conversation_runtime_gateway,
)
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    AdmittedPresentationPin,
    PinSourceUnavailable,
    admit_presentation_pin_reference,
)
from ai_karen_engine.persistence.repositories.chat_run_repository import (
    SqlChatRunRepository,
)
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    PresentationPinRepository,
    StoredPresentationPin,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReauthorizedPresentationPin:
    pin_id: str
    position: int
    revision: int
    admitted: AdmittedPresentationPin


class PresentationPinReadback:
    """Projects only currently owned, attested saved-card references.

    A caller MUST supply ChatExecutionContext from verified authentication.
    This service never trusts a user-supplied tenant, role or ownership claim.
    """

    def __init__(
        self,
        *,
        repository: PresentationPinRepository | None = None,
        gateway: ConversationRuntimeGateway | None = None,
        run_repository: SqlChatRunRepository | None = None,
    ) -> None:
        self._repository = repository or PresentationPinRepository()
        self._gateway = gateway or get_conversation_runtime_gateway()
        self._runs = run_repository or SqlChatRunRepository()

    async def list_authorized(
        self, *, context: ChatExecutionContext
    ) -> tuple[ReauthorizedPresentationPin, ...]:
        # The IDs carried by ChatExecutionContext alone are not a grant. The
        # canonical ingress principal must still match both scopes and remain
        # active and verified before ANY persisted pin reference is read.
        context.require_authenticated_user()
        if not context.tenant_id or not context.user_id:
            raise PermissionError("Authenticated pin context required")

        # Internal rows are untrusted pointers. Never return them as a direct
        # response, even when the SQL query and table RLS are tenant-scoped.
        raw = await self._repository.read_unverified_references(
            authenticated_tenant_id=context.tenant_id,
            authenticated_user_id=context.user_id,
        )
        result: list[ReauthorizedPresentationPin] = []
        authorized: dict[str, tuple[ConversationSnapshot, dict[str, tuple[str, str]]] | None] = {}

        for pin in raw:
            # Explicit principal guard in addition to RLS and the gateway.
            if pin.tenant_id != context.tenant_id or pin.user_id != context.user_id:
                logger.warning(
                    "Pin reference principal mismatch",
                    extra={"event": "presentation_pin_scope_rejected"},
                )
                continue
            thread = pin.reference.conversation_id
            if thread not in authorized:
                owned_context = replace(
                    context, conversation_id=thread, session_id=thread
                )
                try:
                    snapshot = await self._gateway.get_owned_snapshot(
                        owned_context, message_limit=501
                    )
                    attestations = await self._runs.completed_replay_attestations(
                        tenant_id=context.tenant_id,
                        user_id=context.user_id,
                        conversation_id=thread,
                    )
                except PermissionError:
                    # Distinguish authorization denial from operational failure.
                    authorized[thread] = None
                    logger.info(
                        "Pin source no longer authorized",
                        extra={"event": "presentation_pin_origin_denied"},
                    )
                except RuntimeError as exc:
                    if str(exc) != "conversation_not_found":
                        raise
                    authorized[thread] = None
                else:
                    authorized[thread] = (snapshot, attestations)

            proof = authorized[thread]
            if proof is None:
                continue
            snapshot, attestations = proof
            try:
                admitted = admit_presentation_pin_reference(
                    snapshot=snapshot,
                    authenticated_tenant_id=context.tenant_id,
                    authenticated_user_id=context.user_id,
                    reference=pin.reference,
                    attestations=attestations,
                )
            except PinSourceUnavailable:
                logger.info(
                    "Pin source attestation no longer valid",
                    extra={"event": "presentation_pin_origin_unverified"},
                )
                continue
            result.append(ReauthorizedPresentationPin(
                pin_id=pin.pin_id,
                position=pin.position,
                revision=pin.revision,
                admitted=admitted,
            ))
        return tuple(result)

"""KUI-002D3B2: authenticated runtime coordination of atomic pin mutations.

This is the runtime authority for source acquisition and principal validation;
the canonical presentation-pin repository owns transaction and receipt writes.
No HTTP handler, dock control, or independent orchestrator is enabled here.
"""

from __future__ import annotations

from dataclasses import replace

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    get_conversation_runtime_gateway,
)
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PresentationPinReference,
)
from ai_karen_engine.persistence.repositories.chat_run_repository import (
    SqlChatRunRepository,
)
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    CommittedPinMutationReceipt,
    PresentationPinRepository,
)


class PresentationPinMutation:
    """Obtain trusted proof and delegate mutation to the single SQL owner."""

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

    @staticmethod
    def mutations_enabled(features: object) -> bool:
        """Canonical server-side feature decision, never a client grant."""
        return bool(
            getattr(features, "enable_ag_ui_bridge", False)
            and getattr(features, "enable_ag_ui_durable_runs", False)
            and getattr(features, "enable_presentation_pin_mutations", False)
        )

    @classmethod
    def describe_capabilities(
        cls, *, context: ChatExecutionContext, features: object
    ) -> dict[str, object]:
        """Describe server execution eligibility for a verified principal.

        This is advisory presentation metadata, not a bearer capability.
        The mutation executor must independently authenticate and recheck
        the canonical server gate for every write.
        """
        context.require_authenticated_user()
        if not (
            context.tenant_id and context.user_id
            and context.request_id and context.correlation_id
        ):
            raise PermissionError("Authenticated pin capability context required")
        eligible = cls.mutations_enabled(features)
        return {
            "schema_version": 1,
            "mutation_enabled": eligible,
            "allowed_operations": ["unpin", "reorder"] if eligible else [],
            "denial_reason": None if eligible else "mutations_disabled",
        }

    async def execute(
        self,
        *,
        context: ChatExecutionContext,
        idempotency_key: str,
        operation: str,
        reference: PresentationPinReference | None = None,
        pin_id: str | None = None,
        expected_revision: int | None = None,
        position: int | None = None,
    ) -> CommittedPinMutationReceipt:
        """Require a real principal and fresh source proof for all PIN writes.

        The caller cannot pass tenant/user IDs or completed-run attestations.
        An invalid principal fails before accessing any service or database.
        """
        context.require_authenticated_user()
        if (
            not context.tenant_id
            or not context.user_id
            or not context.request_id
            or not context.correlation_id
        ):
            raise PermissionError("Authenticated pin mutation context required")

        snapshot = None
        attestations = None
        if operation == "pin":
            if not isinstance(reference, PresentationPinReference):
                raise ValueError("PIN requires a presentation reference")
            committed = await self._repository.replay_committed_pin_receipt(
                authenticated_tenant_id=context.tenant_id,
                authenticated_user_id=context.user_id,
                idempotency_key=idempotency_key,
                reference=reference,
                position=position if position is not None else 0,
            )
            if committed is not None:
                return committed
            owned = replace(
                context,
                conversation_id=reference.conversation_id,
                session_id=reference.conversation_id,
            )
            snapshot = await self._gateway.get_owned_snapshot(
                owned, message_limit=501
            )
            attestations = await self._runs.completed_replay_attestations(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                conversation_id=reference.conversation_id,
            )

        return await self._repository.mutate_with_receipt(
            authenticated_tenant_id=context.tenant_id,
            authenticated_user_id=context.user_id,
            idempotency_key=idempotency_key,
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            operation=operation,
            pin_id=pin_id,
            expected_revision=expected_revision,
            position=position,
            reference=reference,
            owned_snapshot=snapshot,
            completed_run_attestations=attestations,
        )

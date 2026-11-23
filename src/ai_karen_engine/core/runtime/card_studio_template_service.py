"""Runtime-owned admission and persistence coordination for Card Studio drafts.

This service is the only execution entrypoint for authenticated Card Studio CRUD.
The existing RuntimePolicy evaluates explicit RBAC capabilities; the canonical
CardStudioTemplateRepository remains the sole owner of database mutation,
compare-and-swap, immutable revision history and idempotency receipts.

No route, plugin, template body or model content may choose an identity, mint a
policy grant, publish a card or execute a renderer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardStudioTemplateRepository,
    CardTemplateMutationReceipt,
    SavedCardTemplate,
)
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = logging.getLogger(__name__)

_CAPABILITIES = {
    "read": ("card_studio.read", Permission.CARD_STUDIO_READ),
    "write": ("card_studio.write", Permission.CARD_STUDIO_WRITE),
}


class CardStudioAuthorizationError(PermissionError):
    """Authenticated policy or principal cannot authorize this operation."""


@dataclass(frozen=True, slots=True)
class CardStudioMutation:
    """Committed database result. Never represents a pending write."""

    template: SavedCardTemplate
    receipt: CardTemplateMutationReceipt


class CardStudioTemplateService:
    """Keep authorization and auditing out of both transport and SQL."""

    def __init__(
        self,
        *,
        repository: CardStudioTemplateRepository | None = None,
        policy: RuntimePolicyEnforcer | None = None,
    ) -> None:
        self._repository = repository or CardStudioTemplateRepository()
        self._policy = policy or RuntimePolicyEnforcer()

    @staticmethod
    def _audit(
        context: ChatExecutionContext,
        *,
        operation: str,
        event_type: AuditEventType,
        authorized: bool,
        template_id: str | None = None,
        revision: int | None = None,
        latency_ms: float | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            severity=AuditSeverity.INFO if authorized else AuditSeverity.WARNING,
            message=f"card_studio_{operation}_{'allowed' if authorized else 'denied'}",
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            session_id=context.session_id,
            correlation_id=context.correlation_id,
            metadata={
                "resource": "card_studio.template",
                "operation": operation,
                "template_id": template_id,
                "revision": revision,
                "request_id": context.request_id,
                "latency_ms": latency_ms,
            },
        )
        get_audit_logger().log_audit_event(event)

    @staticmethod
    def _require_principal(context: ChatExecutionContext) -> None:
        if not isinstance(context, ChatExecutionContext):
            raise CardStudioAuthorizationError("Trusted runtime context required")
        try:
            principal = context.require_authenticated_user()
            if not context.request_id or not context.correlation_id:
                raise ValueError("Missing runtime trace identity")
            for value in (principal.user_id, principal.tenant_id):
                raw = str(value or "")
                if str(UUID(raw)) != raw or raw == str(UUID(int=0)):
                    raise ValueError("Invalid authenticated scope")
        except (PermissionError, TypeError, ValueError, AttributeError) as exc:
            raise CardStudioAuthorizationError("Verified Card Studio principal required") from exc

    async def _authorize(
        self, context: ChatExecutionContext, *, operation: str, access: str
    ) -> None:
        self._require_principal(context)
        capability, _ = _CAPABILITIES[access]
        principal = context.require_authenticated_user()
        decision = await self._policy.evaluate(
            PolicyEvaluationRequest(
                user_id=context.user_id,
                tenant_id=context.tenant_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                roles=list(principal.roles),
                permissions=list(principal.permissions),
                action=capability,
                requested_capabilities=[capability],
                max_model_calls=0,
            )
        )
        allowed = bool(
            decision.allowed
            and capability in decision.allowed_capabilities
            and capability not in decision.denied_capabilities
            and decision.runtime_constraints.get("authorized_user_id") == context.user_id
            and decision.runtime_constraints.get("authorized_tenant_id") == context.tenant_id
            and decision.runtime_constraints.get("correlation_id") == context.correlation_id
        )
        self._audit(
            context,
            operation=operation,
            event_type=AuditEventType.ACCESS_GRANTED if allowed else AuditEventType.ACCESS_DENIED,
            authorized=allowed,
        )
        if not allowed:
            raise CardStudioAuthorizationError("Card Studio permission denied")

    async def list_owned(
        self, *, context: ChatExecutionContext, limit: int = 20,
        include_archived: bool = False,
    ) -> list[SavedCardTemplate]:
        await self._authorize(context, operation="list", access="read")
        return await self._repository.list_owned(
            authenticated_tenant_id=context.tenant_id,
            authenticated_user_id=context.user_id,
            limit=limit,
            include_archived=include_archived,
        )

    async def read_owned(
        self, *, context: ChatExecutionContext, template_id: str,
        revision: int | None = None,
    ) -> SavedCardTemplate:
        await self._authorize(context, operation="read", access="read")
        return await self._repository.read_owned(
            authenticated_tenant_id=context.tenant_id,
            authenticated_user_id=context.user_id,
            template_id=template_id,
            revision=revision,
        )

    async def list_revisions(
        self, *, context: ChatExecutionContext, template_id: str,
        limit: int = 20,
    ) -> list[SavedCardTemplate]:
        await self._authorize(context, operation="history", access="read")
        return await self._repository.list_revisions(
            authenticated_tenant_id=context.tenant_id,
            authenticated_user_id=context.user_id,
            template_id=template_id,
            limit=limit,
        )

    async def mutate(
        self, *, context: ChatExecutionContext,
        operation: str, idempotency_key: str,
        draft: dict[str, Any] | None = None,
        template_id: str | None = None,
        expected_revision: int | None = None,
    ) -> CardStudioMutation:
        """Commit or deterministically replay exactly one allowed operation."""
        if operation not in ("create", "revise", "archive"):
            raise ValueError("Unsupported Card Studio mutation")
        await self._authorize(context, operation=operation, access="write")
        scope = {
            "authenticated_tenant_id": context.tenant_id,
            "authenticated_user_id": context.user_id,
            "idempotency_key": idempotency_key,
        }
        started = time.perf_counter()
        try:
            if operation == "create":
                if draft is None or template_id is not None or expected_revision is not None:
                    raise ValueError("Invalid create shape")
                saved, receipt = await self._repository.create_draft(
                    **scope, draft=draft,
                )
            elif operation == "revise":
                if draft is None or template_id is None or expected_revision is None:
                    raise ValueError("Invalid revise shape")
                saved, receipt = await self._repository.revise_draft(
                    **scope,
                    template_id=template_id,
                    expected_revision=expected_revision,
                    draft=draft,
                )
            else:
                if draft is not None or template_id is None or expected_revision is None:
                    raise ValueError("Invalid archive shape")
                saved, receipt = await self._repository.archive_draft(
                    **scope,
                    template_id=template_id,
                    expected_revision=expected_revision,
                )
        except Exception as exc:
            logger.warning(
                "card_studio_mutation_not_confirmed",
                extra={
                    "event": "card_studio_mutation_not_confirmed",
                    "request_id": context.request_id,
                    "correlation_id": context.correlation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
            raise

        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        self._audit(
            context,
            operation=operation,
            event_type=AuditEventType.SECURITY_EVENT,
            authorized=True,
            template_id=saved.template_id,
            revision=receipt.revision,
            latency_ms=elapsed_ms,
        )
        logger.info(
            "card_studio_mutation_committed",
            extra={
                "event": "card_studio_mutation_committed",
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "operation": operation,
                "template_id": saved.template_id,
                "revision": receipt.revision,
                "latency_ms": elapsed_ms,
            },
        )
        return CardStudioMutation(template=saved, receipt=receipt)

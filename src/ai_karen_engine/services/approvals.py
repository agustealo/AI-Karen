"""Runtime-owned durable human approval service."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

from ai_karen_engine.audit_logging import (
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.plugin_lifecycle_approval import PluginLifecycleApprovalScope
from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
    get_approval_repository,
)


class ApprovalError(RuntimeError):
    """Base approval lifecycle error."""


class ApprovalNotFoundError(ApprovalError):
    """Approval does not exist in the caller's tenant/user scope."""


class ApprovalStateError(ApprovalError):
    """Approval cannot transition from its current state."""


class ApprovalScopeError(ApprovalError, PermissionError):
    """Approval does not match the request attempting to consume it."""


def _identity(user: UserData) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.tenant_id or "").strip()
    if not user_id or not tenant_id or tenant_id == "default":
        raise ApprovalScopeError("Explicit authenticated user and tenant are required")
    return user_id, tenant_id


def request_fingerprint(
    request: ChatExecutionRequest,
    *,
    lifecycle_scope: Optional[PluginLifecycleApprovalScope] = None,
) -> str:
    """Stable digest over execution-relevant request content.

    Correlation/request IDs and the approval token itself are intentionally
    excluded so an approved request may be resumed through a fresh transport
    attempt without permitting a changed request body.
    """
    payload = {
        "messages": request.messages,
        "tenant_id": request.context.tenant_id,
        "user_id": request.context.user_id,
        "conversation_id": request.context.conversation_id,
        "session_id": request.context.session_id,
        "preferred_provider": request.preferred_provider,
        "preferred_model": request.preferred_model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if lifecycle_scope is not None:
        payload["plugin_lifecycle_scope"] = lifecycle_scope.to_record()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def serialize_request(
    request: ChatExecutionRequest,
    *,
    lifecycle_scope: Optional[PluginLifecycleApprovalScope] = None,
) -> Dict[str, Any]:
    """Persist normalized request plus immutable server-bound action identity."""
    payload = {
        "messages": request.messages,
        "context": {
            "user_id": request.context.user_id,
            "tenant_id": request.context.tenant_id,
            "session_id": request.context.session_id,
            "conversation_id": request.context.conversation_id,
        },
        "preferred_provider": request.preferred_provider,
        "preferred_model": request.preferred_model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }
    if lifecycle_scope is not None:
        payload["plugin_lifecycle_scope"] = lifecycle_scope.to_record()
    return payload


_LIFECYCLE_INTENTS = frozenset({"plugin.lifecycle.enable", "plugin.lifecycle.disable"})


def _require_lifecycle_scope(
    request: ChatExecutionRequest,
    decision: ExecutionDecision,
    scope: Optional[PluginLifecycleApprovalScope],
) -> None:
    """Reject untrusted or unscoped lifecycle approvals before SQL writes."""
    # WS-04A9E: general chat approvals must never issue a first-party
    # document-style consent. They do not bind the independently verified
    # source revision, fresh bearer session, or purpose-separated attestation.
    if (
        isinstance(decision.intent, str)
        and decision.intent.startswith("writing_style.document_consent.")
    ):
        raise ApprovalScopeError(
            "Document style consent requires source-scoped authenticated approval"
        )
    if (
        isinstance(decision.intent, str)
        and decision.intent.startswith("plugin.lifecycle.")
        and decision.intent not in _LIFECYCLE_INTENTS
    ):
        raise ApprovalScopeError("Unsupported plugin lifecycle approval action")
    if decision.intent not in _LIFECYCLE_INTENTS:
        if scope is not None:
            raise ApprovalScopeError("Lifecycle scope does not match the policy intent")
        return
    if not isinstance(scope, PluginLifecycleApprovalScope):
        raise ApprovalScopeError("Plugin lifecycle approval requires a bound scope")
    if decision.intent != "plugin.lifecycle." + scope.action:
        raise ApprovalScopeError("Lifecycle action and policy intent differ")
    try:
        principal = request.context.require_authenticated_user()
        scope.require_matching_context(request.context)
    except (PermissionError, ValueError) as exc:
        raise ApprovalScopeError("Plugin lifecycle approval identity is unverified") from exc
    if (
        not decision.requires_human_gate
        or str(getattr(decision.risk_level, "value", decision.risk_level))
        not in {"high", "critical"}
        or not str(decision.policy_decision_id or "").strip()
        or decision.policy_constraints.get("authorization_status") != "allowed"
    ):
        raise ApprovalScopeError("Plugin lifecycle approval requires fresh policy and human gate")
    from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

    if not get_rbac_manager().has_permission(principal, Permission.ADMIN_PLUGINS_MANAGE):
        raise ApprovalScopeError("Plugin lifecycle management permission required")


class ApprovalService:
    """Lifecycle authority for pre-execution human approval receipts."""

    def __init__(
        self,
        repository: Optional[SqlApprovalRepository] = None,
    ) -> None:
        self._repository = repository or get_approval_repository()
        self._audit = get_audit_logger()

    async def create_for_request(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        *,
        lifecycle_scope: Optional[PluginLifecycleApprovalScope] = None,
    ) -> Dict[str, Any]:
        _require_lifecycle_scope(request, decision, lifecycle_scope)
        risk_level = getattr(decision.risk_level, "value", decision.risk_level)
        record = await self._repository.create(
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
            conversation_id=request.context.conversation_id,
            request_fingerprint=request_fingerprint(request, lifecycle_scope=lifecycle_scope),
            policy_decision_id=decision.policy_decision_id,
            intent=decision.intent,
            risk_level=str(risk_level),
            reason_codes=list(
                dict.fromkeys(
                    [
                        *decision.policy_reason_codes,
                        *decision.reason_codes,
                    ]
                )
            ),
            request_payload=serialize_request(request, lifecycle_scope=lifecycle_scope),
        )
        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_requested",
                "user_id": request.context.user_id,
                "tenant_id": request.context.tenant_id,
                "session_id": request.context.session_id,
                "correlation_id": request.context.correlation_id,
                "metadata": {
                    "approval_id": record["approval_id"],
                    "intent": decision.intent,
                    "risk_level": str(risk_level),
                    "policy_decision_id": decision.policy_decision_id,
                },
            }
        )
        return record

    async def authorize_or_request(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        *,
        lifecycle_scope: Optional[PluginLifecycleApprovalScope] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a pending approval record or consume an approved one.

        A None result means execution is authorized to continue. This method
        never grants policy by itself: it only enforces the human gate already
        required by the current CORTEX/RuntimePolicy decision.
        """
        _require_lifecycle_scope(request, decision, lifecycle_scope)
        approval_id = str(request.metadata.get("approval_id") or "").strip()
        if not decision.requires_human_gate and not approval_id:
            return None
        if not approval_id:
            return await self.create_for_request(
                request, decision, lifecycle_scope=lifecycle_scope,
            )
        try:
            uuid.UUID(approval_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ApprovalScopeError("Approval receipt is invalid") from exc

        current = await self._repository.get(
            approval_id,
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
        )
        if current is None:
            raise ApprovalNotFoundError("Approval not found")

        fingerprint = request_fingerprint(request, lifecycle_scope=lifecycle_scope)
        if current["request_fingerprint"] != fingerprint:
            raise ApprovalScopeError("Approval does not match this request")

        current_risk = str(
            getattr(decision.risk_level, "value", decision.risk_level)
        )
        if (
            current["intent"] != decision.intent
            or current["risk_level"] != current_risk
        ):
            raise ApprovalScopeError(
                "Approval no longer matches the current policy decision"
            )

        if current["status"] == "approved":
            if decision.intent in _LIFECYCLE_INTENTS:
                # Until PluginKernel supplies a verified durable CAS/claim,
                # approval is evidence of consent, not execution authority.
                raise ApprovalStateError(
                    "Plugin lifecycle execution remains revision-fenced and unavailable"
                )
            await self.consume_for_request(
                approval_id, request=request, lifecycle_scope=lifecycle_scope,
            )
            return None
        if current["status"] == "pending":
            return current
        if current["status"] == "rejected":
            raise ApprovalStateError("Approval was rejected")
        if current["status"] == "expired":
            raise ApprovalStateError("Approval expired")
        raise ApprovalStateError("Approval has already been consumed")

    async def build_resume_request(
        self,
        approval_id: str,
        *,
        user: UserData,
        request_id: str,
        correlation_id: str,
        fresh_permissions: Optional[List[str]] = None,
        stream: bool = True,
    ) -> ChatExecutionRequest:
        """Rebuild an approved request using fresh authenticated identity.

        Persisted roles/permissions are deliberately ignored. Authorization is
        recalculated by CORTEX/RuntimePolicy when the rebuilt request re-enters
        ChatRuntime, and the approval receipt is consumed there only after the
        current decision still requires and accepts the same human gate.
        """
        user_id, tenant_id = _identity(user)
        record = await self._repository.get(
            approval_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if record is None:
            raise ApprovalNotFoundError("Approval not found")
        if record["status"] != "approved":
            raise ApprovalStateError(
                f"Approval cannot resume from status {record['status']}"
            )

        if str(record.get("intent") or "").startswith(
            "writing_style.document_consent."
        ):
            raise ApprovalStateError(
                "Document style consent cannot resume through generic chat approval"
            )

        if str(record.get("intent") or "").startswith("plugin.lifecycle."):
            # Generic resume cannot reconstruct an independently verified
            # current manifest/revision: never replay a stored lifecycle plan.
            raise ApprovalStateError(
                "Plugin lifecycle approval requires fresh revision-verified admission"
            )

        payload = dict(record.get("request_payload") or {})
        context = dict(payload.get("context") or {})
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ApprovalStateError("Stored approval request is incomplete")

        session_id = str(context.get("session_id") or "").strip() or None
        conversation_id = str(context.get("conversation_id") or "").strip() or None
        rebuilt = ChatExecutionRequest(
            messages=[dict(message) for message in messages if isinstance(message, dict)],
            context=ChatExecutionContext(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                conversation_id=conversation_id,
                request_id=request_id,
                correlation_id=correlation_id,
                roles=list(user.roles or []),
                permissions=list(fresh_permissions or []),
            ),
            preferred_provider=payload.get("preferred_provider"),
            preferred_model=payload.get("preferred_model"),
            temperature=float(payload.get("temperature", 0.7)),
            max_tokens=payload.get("max_tokens"),
            stream=stream,
            metadata={
                "transport": "approval_resume",
                "approval_id": approval_id,
            },
        )
        if not rebuilt.messages:
            raise ApprovalStateError("Stored approval request has no valid messages")
        return rebuilt

    async def list_actionable(
        self,
        *,
        user: UserData,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        user_id, tenant_id = _identity(user)
        return await self._repository.list_actionable(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def get(self, approval_id: str, *, user: UserData) -> Dict[str, Any]:
        user_id, tenant_id = _identity(user)
        record = await self._repository.get(
            approval_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if record is None:
            raise ApprovalNotFoundError("Approval not found")
        return record

    async def decide(
        self,
        approval_id: str,
        *,
        user: UserData,
        decision: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_id, tenant_id = _identity(user)
        # A generic chat approval decision is not a bearer-verified author
        # confirmation and must never decide a document consent request.
        current = await self._repository.get(
            approval_id, tenant_id=tenant_id, user_id=user_id,
        )
        if (
            current is not None
            and str(current.get("intent") or "").startswith(
                "writing_style.document_consent."
            )
        ):
            raise ApprovalScopeError(
                "Document author consent requires fresh bearer confirmation"
            )
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "rejected"}:
            raise ApprovalStateError("Decision must be approved or rejected")
        record = await self._repository.decide(
            approval_id,
            tenant_id=tenant_id,
            user_id=user_id,
            decision=normalized,
            reason=(reason or "").strip() or None,
            decided_by=user_id,
        )
        if record is None:
            current = await self._repository.get(
                approval_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            if current is None:
                raise ApprovalNotFoundError("Approval not found")
            if current["status"] == normalized:
                return current
            raise ApprovalStateError(
                f"Approval cannot be decided from status {current['status']}"
            )

        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_decided",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "metadata": {
                    "approval_id": approval_id,
                    "decision": normalized,
                },
            }
        )
        return record

    async def request_document_consent(
        self,
        *,
        request: "Request",
        scope: "DocumentConsentApprovalScope",
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Create a pending source-bound author approval, never the consent."""
        from ai_karen_engine.auth.session import get_document_style_consent_context
        from ai_karen_engine.core.runtime.document_consent_approval import (
            DocumentConsentApprovalScope,
        )
        from ai_karen_engine.persistence.postgres.transactions import (
            async_transaction_scope,
        )
        from ai_karen_engine.services.postgres_document_style_consent_issuer import (
            PostgresDocumentStyleConsentIssuer,
        )
        from ai_karen_engine.services.writing_style_profile_repository import (
            WritingStyleProfileRepository,
        )

        if not isinstance(scope, DocumentConsentApprovalScope):
            raise ApprovalScopeError("Valid author consent scope required")
        if scope.action != "issue":
            raise ApprovalScopeError("Unsupported consent request action")
        context = await get_document_style_consent_context(request)
        scope.require_matching_context(context)
        if (
            not isinstance(correlation_id, str)
            or not 1 <= len(correlation_id) <= 128
        ):
            raise ApprovalScopeError("Invalid consent correlation")

        # The issuer rechecks canonical SHA-256 and profile state in the
        # final atomic transaction. Admission checks those facts first.
        async with async_transaction_scope(scope.tenant_id) as session:
            await WritingStyleProfileRepository._scope(
                session, scope.tenant_id, scope.author_actor_id
            )
            digest = await PostgresDocumentStyleConsentIssuer._read_source_digest(
                session,
                tenant_id=scope.tenant_id,
                actor_id=scope.author_actor_id,
                profile_id=scope.profile_id,
                artifact_id=scope.artifact_id,
            )
        if digest != scope.source_sha256:
            raise ApprovalScopeError("Current document cannot be authorized")

        record = await self._repository.create(
            tenant_id=scope.tenant_id,
            user_id=scope.author_actor_id,
            conversation_id=None,
            request_fingerprint=scope.fingerprint(),
            policy_decision_id=None,
            intent="writing_style.document_consent.issue",
            risk_level="high",
            reason_codes=["explicit_document_author_confirmation_required"],
            request_payload={"document_consent_scope": scope.to_record()},
            ttl_minutes=15,
        )
        self._audit.log_audit_event({
            "event_type": AuditEventType.SECURITY_EVENT,
            "severity": AuditSeverity.INFO,
            "message": "document_author_consent_requested",
            "user_id": scope.author_actor_id,
            "tenant_id": scope.tenant_id,
            "session_id": scope.session_id,
            "correlation_id": correlation_id,
            "metadata": {
                "approval_id": record["approval_id"],
                "profile_id": scope.profile_id,
                "artifact_id": scope.artifact_id,
            },
        })
        return record

    async def decide_document_consent(
        self,
        approval_id: str,
        *,
        request: "Request",
        scope: "DocumentConsentApprovalScope",
        confirmed: bool,
    ) -> Dict[str, Any]:
        """Approve only explicit author confirmation with fresh bearer scope."""
        from ai_karen_engine.auth.session import get_document_style_consent_context
        from ai_karen_engine.core.runtime.document_consent_approval import (
            DocumentConsentApprovalScope,
        )

        if not isinstance(scope, DocumentConsentApprovalScope):
            raise ApprovalScopeError("Valid author consent scope required")
        if scope.action != "issue":
            raise ApprovalScopeError("Unsupported consent decision action")
        context = await get_document_style_consent_context(request)
        scope.require_matching_context(context)
        if confirmed is not True:
            raise ApprovalScopeError("Explicit author confirmation required")
        try:
            if str(uuid.UUID(approval_id)) != approval_id:
                raise ValueError("Noncanonical approval ID")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ApprovalScopeError("Invalid author consent approval") from exc

        current = await self._repository.get(
            approval_id,
            tenant_id=scope.tenant_id,
            user_id=scope.author_actor_id,
        )
        if (
            current is None
            or current.get("status") != "pending"
            or current.get("intent") != "writing_style.document_consent.issue"
            or current.get("request_fingerprint") != scope.fingerprint()
            or current.get("request_payload", {}).get(
                "document_consent_scope"
            ) != scope.to_record()
        ):
            raise ApprovalScopeError("Author consent confirmation scope mismatch")

        record = await self._repository.decide(
            approval_id,
            tenant_id=scope.tenant_id,
            user_id=scope.author_actor_id,
            decision="approved",
            reason="explicit_author_confirmation",
            decided_by=scope.author_actor_id,
        )
        if record is None:
            raise ApprovalStateError("Author consent approval already decided")
        self._audit.log_audit_event({
            "event_type": AuditEventType.SECURITY_EVENT,
            "severity": AuditSeverity.INFO,
            "message": "document_author_consent_confirmed",
            "user_id": scope.author_actor_id,
            "tenant_id": scope.tenant_id,
            "session_id": scope.session_id,
            "correlation_id": context.correlation_id,
            "metadata": {
                "approval_id": approval_id,
                "profile_id": scope.profile_id,
                "artifact_id": scope.artifact_id,
            },
        })
        return record

    async def consume_for_request(
        self,
        approval_id: str,
        *,
        request: ChatExecutionRequest,
        lifecycle_scope: Optional[PluginLifecycleApprovalScope] = None,
    ) -> Dict[str, Any]:
        if lifecycle_scope is not None:
            lifecycle_scope.require_matching_context(request.context)
            # No current kernel revision authority exists yet. This public
            # method may not be mistaken for an executable approval grant.
            raise ApprovalStateError(
                "Plugin lifecycle execution remains revision-fenced and unavailable"
            )
        current = await self._repository.get(
            approval_id,
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
        )
        if current is not None and str(current.get("intent") or "").startswith(
            "writing_style.document_consent."
        ):
            raise ApprovalScopeError(
                "Document consent requires atomic source-scoped consumption"
            )
        record = await self._repository.consume_approved(
            approval_id,
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
            request_fingerprint=request_fingerprint(request, lifecycle_scope=lifecycle_scope),
        )
        if record is None:
            current = await self._repository.get(
                approval_id,
                tenant_id=request.context.tenant_id,
                user_id=request.context.user_id,
            )
            if current is None:
                raise ApprovalNotFoundError("Approval not found")
            if current["request_fingerprint"] != request_fingerprint(
                request, lifecycle_scope=lifecycle_scope,
            ):
                raise ApprovalScopeError("Approval does not match this request")
            raise ApprovalStateError(
                f"Approval cannot be consumed from status {current['status']}"
            )

        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_consumed",
                "user_id": request.context.user_id,
                "tenant_id": request.context.tenant_id,
                "session_id": request.context.session_id,
                "correlation_id": request.context.correlation_id,
                "metadata": {
                    "approval_id": approval_id,
                    "original_policy_decision_id": record.get(
                        "policy_decision_id"
                    ),
                },
            }
        )
        return record


_approval_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


__all__ = [
    "ApprovalError",
    "ApprovalNotFoundError",
    "ApprovalScopeError",
    "ApprovalService",
    "ApprovalStateError",
    "PluginLifecycleApprovalScope",
    "get_approval_service",
    "request_fingerprint",
    "serialize_request",
]

"""Migration admission gate; never a substitute for NeuroVault authorization.

The caller must obtain fresh, trusted runtime policy independently. This pure
gate rejects mismatched, denied or unverified policy evidence before any writer
is even considered. NeuroVault remains the final enforcement authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from .legacy_persona_preflight import LegacyMigrationPreflight


@dataclass(frozen=True)
class LegacyMigrationWriteAuthority:
    tenant_id: str
    user_id: str
    authorized_tenant_id: str
    authorized_user_id: str
    capability: str
    policy_decision_id: str
    explicitly_granted: bool


@dataclass(frozen=True)
class LegacyMigrationAdmission:
    admitted: bool
    reason_codes: tuple[str, ...]
    tenant_id: str | None = None
    user_id: str | None = None


def admit_legacy_migration(
    preflight: LegacyMigrationPreflight,
    authority: LegacyMigrationWriteAuthority,
) -> LegacyMigrationAdmission:
    reasons: list[str] = []
    if not preflight.eligible or preflight.reason_codes:
        reasons.append("preflight_not_eligible")
    if (
        not authority.tenant_id
        or not authority.user_id
        or authority.tenant_id != authority.authorized_tenant_id
        or authority.user_id != authority.authorized_user_id
    ):
        reasons.append("write_principal_mismatch")
    if authority.capability != "memory.write":
        reasons.append("write_capability_missing")
    if not authority.policy_decision_id.strip():
        reasons.append("policy_decision_missing")
    if authority.explicitly_granted is not True:
        reasons.append("write_not_authorized")
    return LegacyMigrationAdmission(
        not reasons, tuple(reasons),
        tenant_id=authority.tenant_id if not reasons else None,
        user_id=authority.user_id if not reasons else None,
    )


@dataclass(frozen=True)
class LegacyMigrationReplayIdentity:
    """Stable retry identifiers, not an authorization or migration receipt."""

    memory_id: str
    request_id: str
    source_record_id: str


def derive_legacy_migration_replay_identity(
    *,
    admission: LegacyMigrationAdmission,
    tenant_id: str,
    user_id: str,
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Produce stable identifiers for NeuroVault's entry+request idempotency.

    The executor must independently verify admission scope and current consent.
    """
    if not admission.admitted or admission.reason_codes:
        raise ValueError("legacy migration admission required")
    try:
        tenant = uuid.UUID(tenant_id)
        user = uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("canonical UUID migration identities required") from exc
    if admission.tenant_id != str(tenant) or admission.user_id != str(user):
        raise ValueError("migration principal does not match admitted scope")
    source = str(source_record_id or "").strip()
    if not source or len(source) > 255:
        raise ValueError("bounded source record identifier required")
    stable = f"ai-karen:persona-memory:v1:{tenant}:{user}:{source}"
    return LegacyMigrationReplayIdentity(
        memory_id=str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ":memory")),
        request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ":request")),
        source_record_id=source,
    )


def prepare_legacy_migration_retry(
    *,
    preflight: "LegacyMigrationPreflight",
    authority: LegacyMigrationWriteAuthority,
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Prepare a retry only if every independent gate agrees.

    This is a pure computation, not a migration executor. All supplied facts
    must be independently authenticated and rechecked immediately before the
    canonical NeuroVault persist operation.
    """
    from .legacy_persona_recovery import requires_fresh_migration_authorization

    if not requires_fresh_migration_authorization(recovery):
        raise ValueError("migration recovery does not allow retry")
    admission = admit_legacy_migration(preflight, authority)
    if not admission.admitted:
        raise ValueError("current migration authorization required")
    return derive_legacy_migration_replay_identity(
        admission=admission,
        tenant_id=authority.tenant_id,
        user_id=authority.user_id,
        source_record_id=source_record_id,
    )


def migration_write_authority_from_policy(
    *,
    request: "PolicyEvaluationRequest",
    decision: "PolicyDecision",
) -> LegacyMigrationWriteAuthority:
    """Interpret an existing RuntimePolicy decision without issuing a new grant.

    Both trusted permission context and the decision must contain memory.write.
    The caller must construct the request from authenticated ingress identity,
    not legacy rows or client-supplied claims.
    """
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyDecision, PolicyEvaluationRequest,
    )

    if not isinstance(request, PolicyEvaluationRequest) or not isinstance(decision, PolicyDecision):
        raise TypeError("canonical RuntimePolicy request and decision required")
    scope = decision.runtime_constraints or {}
    granted = (
        decision.allowed is True
        and request.action == "legacy_persona_memory_migration"
        and "memory.write" in request.permissions
        and "memory.write" in request.requested_capabilities
        and "memory.write" in decision.allowed_capabilities
        and "memory.write" not in decision.denied_capabilities
        and scope.get("authorized_tenant_id") == request.tenant_id
        and scope.get("authorized_user_id") == request.user_id
        and bool(decision.decision_id)
        and not decision.requires_human_gate
    )
    return LegacyMigrationWriteAuthority(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        authorized_tenant_id=str(scope.get("authorized_tenant_id") or ""),
        authorized_user_id=str(scope.get("authorized_user_id") or ""),
        capability="memory.write",
        policy_decision_id=decision.decision_id,
        explicitly_granted=granted,
    )


async def evaluate_migration_write_authority(
    *,
    authenticated_request: "PolicyEvaluationRequest",
    runtime_policy: "RuntimePolicyEnforcer",
) -> LegacyMigrationWriteAuthority:
    """Evaluate live policy from trusted ingress context before admission.

    The request must be built by canonical runtime code using authenticated
    principal and permissions. Never accept it from legacy rows or client JSON.
    """
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )

    if not isinstance(authenticated_request, PolicyEvaluationRequest):
        raise TypeError("canonical authenticated policy request required")
    if not isinstance(runtime_policy, RuntimePolicyEnforcer):
        raise TypeError("canonical RuntimePolicy enforcer required")
    if authenticated_request.action != "legacy_persona_memory_migration":
        raise ValueError("migration-specific runtime policy action required")
    decision = await runtime_policy.evaluate(authenticated_request)
    return migration_write_authority_from_policy(
        request=authenticated_request, decision=decision,
    )


async def prepare_consented_legacy_migration_retry(
    *,
    preflight: "LegacyMigrationPreflight",
    authority: LegacyMigrationWriteAuthority,
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Reconcile canonical affirmative consent before preparing a retry.

    Caller still owns authenticated identity, source validation, retention and
    fresh RuntimePolicy evaluation. This helper does not execute a write.
    """
    from ai_karen_engine.platform.memory.postgres.legacy_persona_consent import (
        verify_legacy_migration_consent,
    )
    if not recovery.safe_to_retry or recovery.already_persisted:
        raise ValueError("migration recovery does not allow retry")
    if not preflight.eligible or preflight.reason_codes:
        raise ValueError("migration preflight not eligible")
    admission = admit_legacy_migration(preflight, authority)
    if not admission.admitted:
        raise ValueError("current migration authorization required before consent lookup")
    if not await verify_legacy_migration_consent(
        tenant_id=authority.tenant_id, user_id=authority.user_id,
        consent_scope="persona-memory-migration",
    ):
        raise ValueError("explicit historical migration consent required")
    return prepare_legacy_migration_retry(
        preflight=preflight, authority=authority,
        recovery=recovery, source_record_id=source_record_id,
    )


async def prepare_runtime_authorized_legacy_migration_retry(
    *,
    authenticated_request: "PolicyEvaluationRequest",
    runtime_policy: "RuntimePolicyEnforcer",
    preflight: "LegacyMigrationPreflight",
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Gate retry on a fresh real policy decision and current ledger consent.

    The runtime must construct authenticated_request and preflight from trusted
    identity, source, and retention evidence. No writes happen here.
    """
    authority = await evaluate_migration_write_authority(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
    )
    if not authority.explicitly_granted:
        raise ValueError("current migration authorization required")
    return await prepare_consented_legacy_migration_retry(
        preflight=preflight,
        authority=authority,
        recovery=recovery,
        source_record_id=source_record_id,
    )


async def prepare_source_verified_legacy_migration_retry(
    *,
    authenticated_request: "PolicyEvaluationRequest",
    runtime_policy: "RuntimePolicyEnforcer",
    preflight: "LegacyMigrationPreflight",
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Read-only source presence check before live policy and consent gates.

    Authenticated request and preflight must be assembled by the canonical
    runtime from trustworthy identity, retention, and provenance evidence.
    Presence alone never grants import permissions or access to record content.
    """
    authority = await evaluate_migration_write_authority(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
    )
    if not authority.explicitly_granted:
        raise ValueError("current migration authorization required before source lookup")
    from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
        verify_legacy_persona_source,
    )
    if not await verify_legacy_persona_source(
        tenant_id=authenticated_request.tenant_id,
        user_id=authenticated_request.user_id,
        source_record_id=source_record_id,
    ):
        raise ValueError("matching nonempty legacy source not verified")
    return await prepare_runtime_authorized_legacy_migration_retry(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
        preflight=preflight,
        recovery=recovery,
        source_record_id=source_record_id,
    )


async def prepare_retention_verified_legacy_migration_retry(
    *,
    authenticated_request: "PolicyEvaluationRequest",
    runtime_policy: "RuntimePolicyEnforcer",
    preflight: "LegacyMigrationPreflight",
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Require source-derived timestamp/class and canonical unexpired TTL.

    This remains read-only preparation, not an identity, consent or write grant.
    """
    authority = await evaluate_migration_write_authority(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
    )
    if not authority.explicitly_granted:
        raise ValueError("current migration authorization required before source lookup")
    from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
        read_legacy_persona_source_retention_metadata,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_retention import (
        verify_legacy_migration_retention,
    )

    metadata = await read_legacy_persona_source_retention_metadata(
        tenant_id=authenticated_request.tenant_id,
        user_id=authenticated_request.user_id,
        source_record_id=source_record_id,
    )
    if metadata is None:
        raise ValueError("verified historical retention metadata required")
    created_at, memory_class = metadata
    if not await verify_legacy_migration_retention(
        tenant_id=authenticated_request.tenant_id,
        created_at=created_at,
        memory_class=memory_class,
    ):
        raise ValueError("historical memory retention not authorized")
    return await prepare_source_verified_legacy_migration_retry(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
        preflight=preflight,
        recovery=recovery,
        source_record_id=source_record_id,
    )


async def prepare_identity_verified_legacy_migration_retry(
    *,
    authenticated_request: "PolicyEvaluationRequest",
    runtime_policy: "RuntimePolicyEnforcer",
    preflight: "LegacyMigrationPreflight",
    recovery: "LegacyReplayRecoveryDecision",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Require exact canonical active identity before historical source checks."""
    from ai_karen_engine.platform.memory.postgres.legacy_persona_identity import (
        verify_legacy_persona_identity,
    )
    authority = await evaluate_migration_write_authority(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
    )
    if not authority.explicitly_granted:
        raise ValueError("current migration authorization required before identity lookup")
    if not isinstance(source_record_id, str) or not source_record_id.strip() or len(source_record_id.strip()) > 64:
        raise ValueError("valid legacy source identifier required before identity lookup")
    if not await verify_legacy_persona_identity(
        tenant_id=authenticated_request.tenant_id,
        user_id=authenticated_request.user_id,
    ):
        raise ValueError("canonical migration identity not verified")
    return await prepare_retention_verified_legacy_migration_retry(
        authenticated_request=authenticated_request,
        runtime_policy=runtime_policy,
        preflight=preflight,
        recovery=recovery,
        source_record_id=source_record_id,
    )


def migration_policy_request_from_runtime_context(
    *, context: "ChatExecutionContext",
) -> "PolicyEvaluationRequest":
    """Build migration policy input from the runtime's canonical context.

    Call only after authenticated ingress establishes the runtime context.
    This adapter cannot authenticate a manually constructed context, and is
    deliberately not an API or a migration execution authorization.
    """
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import PolicyEvaluationRequest

    if not isinstance(context, ChatExecutionContext):
        raise TypeError("canonical runtime execution context required")
    try:
        tenant = str(uuid.UUID(context.tenant_id))
        user = str(uuid.UUID(context.user_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("canonical scoped runtime principal required") from exc
    if not context.session_id or not str(context.session_id).strip():
        raise ValueError("authenticated runtime session required")
    if not context.request_id or not str(context.request_id).strip():
        raise ValueError("runtime request identifier required")
    if not context.correlation_id or not str(context.correlation_id).strip():
        raise ValueError("runtime correlation identifier required")
    return PolicyEvaluationRequest(
        tenant_id=tenant,
        user_id=user,
        session_id=context.session_id,
        correlation_id=context.correlation_id,
        roles=list(context.roles),
        permissions=list(context.permissions),
        action="legacy_persona_memory_migration",
        requested_capabilities=["memory.write"],
    )


async def prepare_governed_legacy_migration_retry(
    *,
    context: "ChatExecutionContext",
    runtime_policy: "RuntimePolicyEnforcer",
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Read-only, single-policy-evaluation preparation from canonical runtime.

    This does not authenticate ingress, fetch source content, or persist memory.
    Only an authenticated runtime caller may supply context; NeuroVault must
    independently reauthorize and check live consent at the eventual write.
    """
    from ai_karen_engine.core.memory.legacy_persona_preflight import (
        LegacyMigrationEvidence, preflight_legacy_memory,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import reconcile_legacy_replay
    from ai_karen_engine.platform.memory.postgres.legacy_persona_identity import (
        verify_legacy_persona_identity,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
        read_legacy_persona_source_retention_metadata,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_retention import (
        verify_legacy_migration_retention,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_consent import (
        verify_legacy_migration_consent,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
        lookup_legacy_replay_receipt,
    )

    request = migration_policy_request_from_runtime_context(context=context)
    authority = await evaluate_migration_write_authority(
        authenticated_request=request, runtime_policy=runtime_policy,
    )
    if not authority.explicitly_granted:
        raise ValueError("current migration authorization required before database reads")
    if (
        not isinstance(source_record_id, str)
        or not source_record_id.strip()
        or len(source_record_id.strip()) > 64
    ):
        raise ValueError("valid legacy source identifier required before database reads")
    source = source_record_id.strip()
    tenant, user = request.tenant_id, request.user_id

    if not await verify_legacy_persona_identity(tenant_id=tenant, user_id=user):
        raise ValueError("canonical migration identity not verified")
    metadata = await read_legacy_persona_source_retention_metadata(
        tenant_id=tenant, user_id=user, source_record_id=source,
    )
    if metadata is None:
        raise ValueError("verified historical retention metadata required")
    created_at, memory_class = metadata
    if not await verify_legacy_migration_retention(
        tenant_id=tenant, created_at=created_at, memory_class=memory_class,
    ):
        raise ValueError("historical memory retention not authorized")
    if not await verify_legacy_migration_consent(
        tenant_id=tenant, user_id=user, consent_scope="persona-memory-migration",
    ):
        raise ValueError("explicit historical migration consent required")

    preflight = preflight_legacy_memory(LegacyMigrationEvidence(
        legacy_tenant_id=tenant, legacy_user_id=user,
        authorized_tenant_id=tenant, authorized_user_id=user,
        identity_verified=True, consent_verified=True, retention_verified=True,
        source_record_verified=True, evidence_origin="authorized_runtime",
    ))
    admission = admit_legacy_migration(preflight, authority)
    if not admission.admitted:
        raise ValueError("current migration admission required")
    replay = derive_legacy_migration_replay_identity(
        admission=admission, tenant_id=tenant, user_id=user, source_record_id=source,
    )
    receipt = await lookup_legacy_replay_receipt(
        tenant_id=tenant, user_id=user, expected_memory_id=replay.memory_id,
        expected_request_id=replay.request_id,
    )
    recovery = reconcile_legacy_replay(receipt)
    from ai_karen_engine.core.memory.legacy_persona_recovery import (
        requires_fresh_migration_authorization,
    )
    if not requires_fresh_migration_authorization(recovery):
        raise ValueError("migration recovery does not allow retry")
    return replay


async def migration_policy_request_from_authenticated_http(
    *, request: "Request", request_id: str, correlation_id: str,
) -> "PolicyEvaluationRequest":
    """Fail-closed HTTP credential boundary; read-only, no migration execution.

    Authenticate directly through the existing middleware instead of trusting
    request.state.user or a caller-constructed ChatExecutionContext. Historical
    operations require functioning revocation storage, even if ordinary chat
    tolerates a degraded auth revocation backend.
    """
    from fastapi import Request
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.auth.auth_middleware import (
        AuthenticationError, get_auth_middleware,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

    if not isinstance(request, Request):
        raise TypeError("canonical HTTP request required")
    if auth_config.should_bypass_auth():
        raise PermissionError("historical migration forbidden with auth bypass")
    middleware = get_auth_middleware()
    store = middleware.redis_client
    if store is None:
        raise PermissionError("historical migration requires revocation store")
    try:
        store.ping()
        token = middleware._extract_token_from_request(request)
        if not token:
            raise PermissionError("historical migration requires access token")
        payload = middleware._decode_jwt(token)
        token_id = str(payload.get("token_id") or "").strip()
        if not token_id:
            raise PermissionError("historical migration token invalid or revoked")
        # Check the revocation store directly because the generic middleware
        # intentionally degrades to not-revoked when its lookup fails.
        if store.exists(middleware._get_redis_key("revoked", token_id)):
            raise PermissionError("historical migration token revoked")
        principal = middleware._get_user_from_payload(payload)
        if "memory.write" not in (principal.get("permissions") or []):
            raise PermissionError("historical migration write permission required")
        if not request_id or not request_id.strip() or not correlation_id or not correlation_id.strip():
            raise ValueError("request and correlation identity required")
        context = ChatExecutionContext(
            tenant_id=principal["tenant_id"], user_id=principal["user_id"],
            session_id=token_id, request_id=request_id,
            correlation_id=correlation_id,
            roles=list(principal.get("roles") or []),
            permissions=list(principal.get("permissions") or []),
        )
        return migration_policy_request_from_runtime_context(context=context)
    except (PermissionError, ValueError, TypeError):
        raise
    except AuthenticationError as exc:
        raise PermissionError("historical migration authentication failed") from exc
    except Exception as exc:
        raise PermissionError("historical migration credential verification unavailable") from exc

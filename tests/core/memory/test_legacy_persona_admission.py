import pytest
"""Migration preflight does not confer write authority."""
from ai_karen_engine.core.memory.legacy_persona_admission import (
    LegacyMigrationWriteAuthority, admit_legacy_migration,
    derive_legacy_migration_replay_identity, prepare_legacy_migration_retry,
)
from ai_karen_engine.core.memory.legacy_persona_preflight import LegacyMigrationPreflight


def authority(**overrides):
    fields = dict(
        tenant_id="tenant-a", authorized_tenant_id="tenant-a",
        user_id="user-a", authorized_user_id="user-a",
        capability="memory.write", policy_decision_id="policy-1",
        explicitly_granted=True,
    )
    fields.update(overrides)
    return LegacyMigrationWriteAuthority(**fields)


def test_eligible_preflight_cannot_override_policy_denial():
    result = admit_legacy_migration(
        LegacyMigrationPreflight(True, ()), authority(explicitly_granted=False)
    )
    assert not result.admitted
    assert "write_not_authorized" in result.reason_codes


def test_write_grant_cannot_override_unverified_source():
    result = admit_legacy_migration(
        LegacyMigrationPreflight(False, ("consent_unverified",)), authority()
    )
    assert not result.admitted
    assert "preflight_not_eligible" in result.reason_codes


def test_cross_principal_and_wrong_capability_denied():
    result = admit_legacy_migration(
        LegacyMigrationPreflight(True, ()),
        authority(authorized_tenant_id="tenant-b", capability="memory.read"),
    )
    assert not result.admitted
    assert "write_principal_mismatch" in result.reason_codes
    assert "write_capability_missing" in result.reason_codes


def test_separately_verified_conditions_only_admit_not_persist():
    result = admit_legacy_migration(LegacyMigrationPreflight(True, ()), authority())
    assert result.admitted
    assert result.reason_codes == ()


def test_migration_replay_identity_is_stable_across_retries():
    from uuid import uuid4
    tenant, user = str(uuid4()), str(uuid4())
    kwargs = dict(
        admission=LegacyMigrationPreflight(True, ()),
        tenant_id=tenant, user_id=user, source_record_id="legacy-row-42",
    )
    # The helper requires a separately admitted decision, not bare preflight.
    kwargs["admission"] = admit_legacy_migration(LegacyMigrationPreflight(True, ()), authority(tenant_id=tenant, authorized_tenant_id=tenant, user_id=user, authorized_user_id=user))
    first = derive_legacy_migration_replay_identity(**kwargs)
    assert first == derive_legacy_migration_replay_identity(**kwargs)
    assert first.memory_id != first.request_id
    assert first != derive_legacy_migration_replay_identity(**{
        **kwargs, "source_record_id": "legacy-row-43",
    })


def test_migration_replay_identity_denied_without_admission():
    import pytest
    from uuid import uuid4
    rejected = admit_legacy_migration(
        LegacyMigrationPreflight(False, ("consent_unverified",)), authority()
    )
    with pytest.raises(ValueError, match="admission"):
        derive_legacy_migration_replay_identity(
            admission=rejected, tenant_id=str(uuid4()),
            user_id=str(uuid4()), source_record_id="legacy-row",
        )


def test_migration_replay_cannot_reuse_admission_for_another_principal():
    import pytest
    from uuid import uuid4
    tenant, user = str(uuid4()), str(uuid4())
    approved = admit_legacy_migration(
        LegacyMigrationPreflight(True, ()),
        authority(tenant_id=tenant, authorized_tenant_id=tenant, user_id=user, authorized_user_id=user),
    )
    with pytest.raises(ValueError, match="does not match admitted scope"):
        derive_legacy_migration_replay_identity(
            admission=approved, tenant_id=str(uuid4()),
            user_id=user, source_record_id="row-1",
        )


def test_retry_preparation_requires_all_three_gates():
    import pytest
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_recovery import (
        LegacyReplayRecoveryDecision,
    )
    tenant, user = str(uuid4()), str(uuid4())
    scoped = authority(tenant_id=tenant, authorized_tenant_id=tenant,
                       user_id=user, authorized_user_id=user)
    missing = LegacyReplayRecoveryDecision(False, True, "no_prior_receipt")
    kwargs = dict(
        preflight=LegacyMigrationPreflight(True, ()),
        authority=scoped, recovery=missing, source_record_id="row-1",
    )
    prepared = prepare_legacy_migration_retry(**kwargs)
    assert prepared == prepare_legacy_migration_retry(**kwargs)
    with pytest.raises(ValueError, match="recovery"):
        prepare_legacy_migration_retry(**{
            **kwargs, "recovery": LegacyReplayRecoveryDecision(True, False, "already_persisted"),
        })
    with pytest.raises(ValueError, match="authorization"):
        prepare_legacy_migration_retry(**{
            **kwargs, "preflight": LegacyMigrationPreflight(False, ("consent_unverified",)),
        })
    with pytest.raises(ValueError, match="authorization"):
        prepare_legacy_migration_retry(**{
            **kwargs, "authority": authority(
                tenant_id=tenant, authorized_tenant_id=tenant,
                user_id=user, authorized_user_id=user, explicitly_granted=False,
            ),
        })


def test_runtime_policy_conversion_requires_trusted_permission_and_matching_scope():
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_write_authority_from_policy,
    )
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyDecision, PolicyEvaluationRequest,
    )
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        requested_capabilities=["memory.write"], permissions=["memory.write"],
    )
    decision = PolicyDecision(
        decision_id="decision-1", policy_version="v2", allowed=True,
        allowed_capabilities=["memory.write"],
        runtime_constraints={"authorized_tenant_id": "tenant-a",
                             "authorized_user_id": "user-a"},
    )
    assert migration_write_authority_from_policy(
        request=request, decision=decision
    ).explicitly_granted
    wrong_action = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="ordinary_memory_write",
        requested_capabilities=["memory.write"], permissions=["memory.write"],
    )
    assert not migration_write_authority_from_policy(
        request=wrong_action, decision=decision
    ).explicitly_granted
    no_permission = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        requested_capabilities=["memory.write"],
    )
    assert not migration_write_authority_from_policy(
        request=no_permission, decision=decision
    ).explicitly_granted
    cross_tenant = PolicyDecision(
        decision_id="decision-2", policy_version="v2", allowed=True,
        allowed_capabilities=["memory.write"],
        runtime_constraints={"authorized_tenant_id": "tenant-b",
                             "authorized_user_id": "user-a"},
    )
    assert not migration_write_authority_from_policy(
        request=request, decision=cross_tenant
    ).explicitly_granted
    human_gate = PolicyDecision(
        decision_id="decision-3", policy_version="v2", allowed=True,
        allowed_capabilities=["memory.write"], requires_human_gate=True,
        runtime_constraints={"authorized_tenant_id": "tenant-a",
                             "authorized_user_id": "user-a"},
    )
    assert not migration_write_authority_from_policy(
        request=request, decision=human_gate
    ).explicitly_granted


@pytest.mark.asyncio
async def test_live_runtime_policy_gate_requires_trusted_permission():
    import pytest
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        evaluate_migration_write_authority,
    )
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    policy = RuntimePolicyEnforcer()
    base = dict(tenant_id="tenant-a", user_id="user-a",
                action="legacy_persona_memory_migration",
                requested_capabilities=["memory.write"])
    allowed = await evaluate_migration_write_authority(
        authenticated_request=PolicyEvaluationRequest(
            **base, permissions=["memory.write"],
        ),
        runtime_policy=policy,
    )
    assert allowed.explicitly_granted
    denied = await evaluate_migration_write_authority(
        authenticated_request=PolicyEvaluationRequest(**base, permissions=[]),
        runtime_policy=policy,
    )
    assert not denied.explicitly_granted
    with pytest.raises(ValueError, match="migration-specific"):
        await evaluate_migration_write_authority(
            authenticated_request=PolicyEvaluationRequest(
                tenant_id="tenant-a", user_id="user-a",
                action="general_assist",
                permissions=["memory.write"],
                requested_capabilities=["memory.write"],
            ),
            runtime_policy=policy,
        )


@pytest.mark.asyncio
async def test_source_verified_retry_denies_missing_source_before_policy(monkeypatch):
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_source_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.platform.memory.postgres import legacy_persona_source
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )

    calls = []
    async def missing_source(**kwargs):
        calls.append(kwargs)
        return False

    monkeypatch.setattr(legacy_persona_source, "verify_legacy_persona_source", missing_source)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        requested_capabilities=["memory.write"], permissions=["memory.write"],
    )
    with pytest.raises(ValueError, match="matching nonempty legacy source"):
        await prepare_source_verified_legacy_migration_retry(
            authenticated_request=request, runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="legacy-123",
        )
    assert calls == [{"tenant_id": "tenant-a", "user_id": "user-a",
                      "source_record_id": "legacy-123"}]


@pytest.mark.asyncio
async def test_legacy_retention_requires_explicit_unexpired_policy(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from ai_karen_engine.platform.memory.postgres import legacy_persona_retention as module

    class FakeResult:
        def __init__(self, policy):
            self.policy = policy
        def scalar_one_or_none(self):
            return self.policy

    class FakeSession:
        def __init__(self, policies):
            self.policies = iter(policies)
        async def execute(self, statement):
            return FakeResult(next(self.policies))

    class FakeScope:
        def __init__(self, policies):
            self.session = FakeSession(policies)
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, *args):
            return False

    now = datetime.now(timezone.utc)
    params = dict(tenant_id="ba8cc62d-ed28-471d-bdda-8545e56e20f5",
                  memory_class="semantic")
    monkeypatch.setattr(module, "async_transaction_scope",
                        lambda **kwargs: FakeScope([None, None]))
    assert not await module.verify_legacy_migration_retention(
        **params, created_at=now - timedelta(days=1))
    monkeypatch.setattr(module, "async_transaction_scope",
                        lambda **kwargs: FakeScope([SimpleNamespace(ttl_days=30)]))
    assert await module.verify_legacy_migration_retention(
        **params, created_at=now - timedelta(days=1))
    monkeypatch.setattr(module, "async_transaction_scope",
                        lambda **kwargs: FakeScope([SimpleNamespace(ttl_days=1)]))
    assert not await module.verify_legacy_migration_retention(
        **params, created_at=now - timedelta(days=10))


@pytest.mark.asyncio
async def test_retention_verified_preparation_denies_missing_or_expired_source(monkeypatch):
    from datetime import datetime, timezone
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_retention_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import legacy_persona_source, legacy_persona_retention

    async def missing(**kwargs):
        return None
    monkeypatch.setattr(legacy_persona_source, "read_legacy_persona_source_retention_metadata", missing)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    opts = dict(
        authenticated_request=request, runtime_policy=RuntimePolicyEnforcer(),
        preflight=LegacyMigrationPreflight(True, ()),
        recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
        source_record_id="legacy-123",
    )
    with pytest.raises(ValueError, match="retention metadata"):
        await prepare_retention_verified_legacy_migration_retry(**opts)
    async def present(**kwargs):
        return datetime.now(timezone.utc), "chat_interaction"
    async def expired(**kwargs):
        return False
    monkeypatch.setattr(legacy_persona_source, "read_legacy_persona_source_retention_metadata", present)
    monkeypatch.setattr(legacy_persona_retention, "verify_legacy_migration_retention", expired)
    with pytest.raises(ValueError, match="retention not authorized"):
        await prepare_retention_verified_legacy_migration_retry(**opts)


@pytest.mark.asyncio
async def test_identity_gate_blocks_unverified_user_before_retention(monkeypatch):
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_identity_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import legacy_persona_identity

    async def unverified(**kwargs):
        assert kwargs == {"tenant_id": "tenant-a", "user_id": "user-a"}
        return False

    monkeypatch.setattr(legacy_persona_identity, "verify_legacy_persona_identity", unverified)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    with pytest.raises(ValueError, match="canonical migration identity"):
        await prepare_identity_verified_legacy_migration_retry(
            authenticated_request=request,
            runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
async def test_unauthorized_migration_denied_before_identity_database_lookup(monkeypatch):
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_identity_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import legacy_persona_identity

    async def unexpected_lookup(**kwargs):
        raise AssertionError("unauthorized request reached identity database")

    monkeypatch.setattr(
        legacy_persona_identity, "verify_legacy_persona_identity", unexpected_lookup,
    )
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        permissions=[], requested_capabilities=["memory.write"],
    )
    with pytest.raises(ValueError, match="current migration authorization"):
        await prepare_identity_verified_legacy_migration_retry(
            authenticated_request=request,
            runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", [
    "prepare_source_verified_legacy_migration_retry",
    "prepare_retention_verified_legacy_migration_retry",
])
async def test_migration_policy_precedes_all_historical_reads(monkeypatch, entrypoint):
    from ai_karen_engine.core.memory import legacy_persona_admission as admission
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import (
        legacy_persona_source, legacy_persona_retention,
    )

    async def forbidden_read(**kwargs):
        raise AssertionError("unauthorized migration performed database read")

    monkeypatch.setattr(legacy_persona_source, "verify_legacy_persona_source", forbidden_read)
    monkeypatch.setattr(legacy_persona_source, "read_legacy_persona_source_retention_metadata", forbidden_read)
    monkeypatch.setattr(legacy_persona_retention, "verify_legacy_migration_retention", forbidden_read)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        permissions=[], requested_capabilities=["memory.write"],
    )
    with pytest.raises(ValueError, match="current migration authorization"):
        await getattr(admission, entrypoint)(
            authenticated_request=request,
            runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
async def test_consented_retry_rejects_unadmitted_policy_evidence_before_consent_read(monkeypatch):
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        LegacyMigrationWriteAuthority, prepare_consented_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.platform.memory.postgres import legacy_persona_consent

    async def fail_on_consent_read(**kwargs):
        raise AssertionError("unadmitted migration queried the consent ledger")

    monkeypatch.setattr(
        legacy_persona_consent, "verify_legacy_migration_consent",
        fail_on_consent_read,
    )
    denied = LegacyMigrationWriteAuthority(
        tenant_id="tenant-a", user_id="user-a",
        authorized_tenant_id="tenant-a", authorized_user_id="user-a",
        capability="memory.write", policy_decision_id="denied-decision",
        explicitly_granted=False,
    )
    with pytest.raises(ValueError, match="authorization required before consent lookup"):
        await prepare_consented_legacy_migration_retry(
            preflight=LegacyMigrationPreflight(True, ()),
            authority=denied,
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", [
    "prepare_identity_verified_legacy_migration_retry",
    "prepare_retention_verified_legacy_migration_retry",
    "prepare_source_verified_legacy_migration_retry",
])
async def test_wrong_migration_action_never_reads_historical_principal(
    monkeypatch, entrypoint,
):
    from ai_karen_engine.core.memory import legacy_persona_admission as admission
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import (
        legacy_persona_identity, legacy_persona_source, legacy_persona_retention,
    )

    async def forbidden_read(**kwargs):
        raise AssertionError("wrong policy action accessed historical identity/source")

    monkeypatch.setattr(legacy_persona_identity, "verify_legacy_persona_identity", forbidden_read)
    monkeypatch.setattr(legacy_persona_source, "verify_legacy_persona_source", forbidden_read)
    monkeypatch.setattr(
        legacy_persona_source, "read_legacy_persona_source_retention_metadata", forbidden_read,
    )
    monkeypatch.setattr(legacy_persona_retention, "verify_legacy_migration_retention", forbidden_read)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="ordinary_memory_write",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    with pytest.raises(ValueError, match="migration-specific runtime policy action"):
        await getattr(admission, entrypoint)(
            authenticated_request=request,
            runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", ["", "  ", "x" * 65, None])
async def test_invalid_legacy_source_id_rejected_before_identity_read(
    monkeypatch, source_id,
):
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_identity_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.platform.memory.postgres import legacy_persona_identity

    async def forbidden_read(**kwargs):
        raise AssertionError("invalid source identifier accessed user records")

    monkeypatch.setattr(legacy_persona_identity, "verify_legacy_persona_identity", forbidden_read)
    request = PolicyEvaluationRequest(
        tenant_id="tenant-a", user_id="user-a",
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    with pytest.raises(ValueError, match="valid legacy source identifier"):
        await prepare_identity_verified_legacy_migration_retry(
            authenticated_request=request,
            runtime_policy=RuntimePolicyEnforcer(),
            preflight=LegacyMigrationPreflight(True, ()),
            recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
            source_record_id=source_id,
        )


def test_migration_policy_request_reuses_canonical_runtime_identity():
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_runtime_context,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

    tenant, user = str(uuid4()), str(uuid4())
    context = ChatExecutionContext(
        tenant_id=tenant, user_id=user, session_id="session-1",
        request_id="request-1", correlation_id="trace-1",
        roles=["member"], permissions=["memory.read"],
    )
    request = migration_policy_request_from_runtime_context(context=context)
    assert request.tenant_id == tenant
    assert request.user_id == user
    assert request.session_id == "session-1"
    assert request.correlation_id == "trace-1"
    assert request.action == "legacy_persona_memory_migration"
    assert request.requested_capabilities == ["memory.write"]
    assert request.permissions == ["memory.read"]


@pytest.mark.parametrize("missing", ["tenant_id", "user_id", "session_id", "request_id", "correlation_id"])
def test_migration_policy_request_rejects_incomplete_runtime_context(missing):
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_runtime_context,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

    fields = dict(tenant_id=str(uuid4()), user_id=str(uuid4()),
                  session_id="session-1", request_id="request-1",
                  correlation_id="trace-1")
    fields[missing] = ""
    with pytest.raises(ValueError):
        migration_policy_request_from_runtime_context(
            context=ChatExecutionContext(**fields)
        )


@pytest.mark.asyncio
async def test_migration_runtime_context_does_not_create_write_permission():
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_runtime_context,
        evaluate_migration_write_authority,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer

    context = ChatExecutionContext(
        tenant_id=str(uuid4()), user_id=str(uuid4()),
        session_id="session-1", request_id="request-1",
        permissions=["memory.read"],
    )
    request = migration_policy_request_from_runtime_context(context=context)
    authority = await evaluate_migration_write_authority(
        authenticated_request=request, runtime_policy=RuntimePolicyEnforcer()
    )
    assert not authority.explicitly_granted


@pytest.mark.asyncio
async def test_governed_migration_evidence_is_read_only_and_scoped(monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_governed_legacy_migration_retry,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayReceiptEvidence
    from ai_karen_engine.platform.memory.postgres import (
        legacy_persona_identity, legacy_persona_source, legacy_persona_retention,
        legacy_persona_consent, legacy_persona_receipts,
    )

    tenant, user = str(uuid4()), str(uuid4())
    calls = []

    async def identity(**kwargs):
        calls.append("identity")
        assert kwargs == {"tenant_id": tenant, "user_id": user}
        return True

    async def source(**kwargs):
        calls.append("source")
        assert kwargs["source_record_id"] == "source-1"
        return datetime.now(timezone.utc), "semantic"

    async def retention(**kwargs):
        calls.append("retention")
        assert kwargs["tenant_id"] == tenant
        return True

    async def consent(**kwargs):
        calls.append("consent")
        assert kwargs["consent_scope"] == "persona-memory-migration"
        return True

    async def receipt(**kwargs):
        calls.append("receipt")
        return LegacyReplayReceiptEvidence(
            expected_memory_id=kwargs["expected_memory_id"],
            expected_tenant_id=tenant, expected_user_id=user,
            persisted_memory_id=None, persisted_tenant_id=None,
            persisted_user_id=None, persisted=False,
        )

    monkeypatch.setattr(legacy_persona_identity, "verify_legacy_persona_identity", identity)
    monkeypatch.setattr(legacy_persona_source, "read_legacy_persona_source_retention_metadata", source)
    monkeypatch.setattr(legacy_persona_retention, "verify_legacy_migration_retention", retention)
    monkeypatch.setattr(legacy_persona_consent, "verify_legacy_migration_consent", consent)
    monkeypatch.setattr(legacy_persona_receipts, "lookup_legacy_replay_receipt", receipt)

    context = ChatExecutionContext(
        tenant_id=tenant, user_id=user, session_id="session-1",
        request_id="request-1", permissions=["memory.write"],
    )
    policy = RuntimePolicyEnforcer()
    replay = await prepare_governed_legacy_migration_retry(
        context=context, runtime_policy=policy, source_record_id="source-1",
    )
    assert replay.source_record_id == "source-1"
    assert calls == ["identity", "source", "retention", "consent", "receipt"]


@pytest.mark.asyncio
async def test_governed_migration_denial_prevents_canonical_reads(monkeypatch):
    from uuid import uuid4
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_governed_legacy_migration_retry,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer
    from ai_karen_engine.platform.memory.postgres import legacy_persona_identity

    async def forbidden_read(**kwargs):
        raise AssertionError("policy-denied request performed a database read")

    monkeypatch.setattr(legacy_persona_identity, "verify_legacy_persona_identity", forbidden_read)
    context = ChatExecutionContext(
        tenant_id=str(uuid4()), user_id=str(uuid4()),
        session_id="session-1", request_id="request-1",
        permissions=["memory.read"],
    )
    with pytest.raises(ValueError, match="authorization required"):
        await prepare_governed_legacy_migration_retry(
            context=context, runtime_policy=RuntimePolicyEnforcer(),
            source_record_id="source-1",
        )


@pytest.mark.asyncio
async def test_migration_http_credentials_denied_during_auth_bypass(monkeypatch):
    from starlette.requests import Request
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_authenticated_http,
    )
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: True)
    request = Request({"type": "http", "method": "POST", "path": "/internal",
                       "headers": [], "query_string": b""})
    with pytest.raises(PermissionError, match="auth bypass"):
        await migration_policy_request_from_authenticated_http(
            request=request, request_id="req", correlation_id="corr",
        )


@pytest.mark.asyncio
async def test_migration_http_requires_live_revocation_store(monkeypatch):
    from starlette.requests import Request
    from ai_karen_engine.auth import auth_middleware
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_authenticated_http,
    )
    class UnavailableAuth:
        redis_client = None
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: UnavailableAuth())
    request = Request({"type": "http", "method": "POST", "path": "/internal",
                       "headers": [], "query_string": b""})
    with pytest.raises(PermissionError, match="revocation store"):
        await migration_policy_request_from_authenticated_http(
            request=request, request_id="req", correlation_id="corr",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["valid", "revoked", "store_failed", "expired", "no_permission"])
async def test_migration_http_credential_authority_scenarios(monkeypatch, scenario):
    from uuid import uuid4
    from starlette.requests import Request
    from ai_karen_engine.auth import auth_middleware
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_authenticated_http,
    )

    tenant, user = str(uuid4()), str(uuid4())
    class Store:
        def ping(self):
            return True
        def exists(self, key):
            if scenario == "store_failed":
                raise ConnectionError("revocation backend offline")
            return int(scenario == "revoked")
    class Auth:
        redis_client = Store()
        def _extract_token_from_request(self, request):
            return "signed-access-token"
        def _decode_jwt(self, token):
            if scenario == "expired":
                raise auth_middleware.AuthenticationError("Token has expired")
            return {"sub": user, "tenant_id": tenant, "token_id": "token-1",
                    "permissions": ["memory.read"] if scenario == "no_permission" else ["memory.write"],
                    "roles": ["admin"]}
        def _get_redis_key(self, prefix, token_id):
            return f"auth:{prefix}:{token_id}"
        def _get_user_from_payload(self, payload):
            return {"user_id": payload["sub"], "tenant_id": payload["tenant_id"],
                    "roles": payload["roles"], "permissions": payload["permissions"]}

    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: Auth())
    request = Request({"type": "http", "method": "POST", "path": "/internal",
                       "headers": [], "query_string": b""})
    if scenario == "valid":
        result = await migration_policy_request_from_authenticated_http(
            request=request, request_id="req", correlation_id="corr",
        )
        assert result.tenant_id == tenant and result.user_id == user
        assert result.permissions == ["memory.write"]
        assert result.action == "legacy_persona_memory_migration"
    else:
        with pytest.raises(PermissionError):
            await migration_policy_request_from_authenticated_http(
                request=request, request_id="req", correlation_id="corr",
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_claims", [
    {"permissions": "memory.write"},
    {"permissions": {"memory.write": True}},
    {"roles": "admin"},
    {"roles": [1]},
])
async def test_migration_http_rejects_malformed_signed_claim_shapes(monkeypatch, bad_claims):
    """A signed token must not turn string membership into an authorization."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    import jwt
    from starlette.requests import Request
    from ai_karen_engine.auth import auth_middleware
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_authenticated_http,
    )

    class Store:
        def ping(self):
            return True
        def exists(self, key):
            return 0

    middleware = auth_middleware.SecureAuthMiddleware.__new__(
        auth_middleware.SecureAuthMiddleware
    )
    middleware.jwt_secret = "kp03-disposable-test-secret"
    middleware.jwt_algorithm = "HS256"
    middleware.redis_client = Store()
    payload = {
        "sub": str(uuid4()), "tenant_id": str(uuid4()),
        "token_id": "kp03-token", "permissions": ["memory.write"],
        "roles": ["admin"], "iss": "ai-karen", "aud": "ai-karen-users",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(bad_claims)
    token = jwt.encode(payload, middleware.jwt_secret, algorithm="HS256")
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
    request = Request({
        "type": "http", "method": "POST", "path": "/internal",
        "headers": [(b"authorization", ("Bearer " + token).encode())],
        "query_string": b"",
    })
    with pytest.raises(PermissionError, match="credential claims invalid"):
        await migration_policy_request_from_authenticated_http(
            request=request, request_id="request-1", correlation_id="trace-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", [
    "valid", "expired", "tampered", "revoked", "store_failure",
    "wrong_tenant", "missing_token_id",
])
async def test_migration_http_real_jwt_integrity_and_revocation(monkeypatch, scenario):
    """Exercise actual JWT decoder and fail-closed revocation read."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    import jwt
    from starlette.requests import Request
    from ai_karen_engine.auth import auth_middleware
    from ai_karen_engine.core.security.auth_config import auth_config
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        migration_policy_request_from_authenticated_http,
    )

    class Store:
        def ping(self):
            return True
        def exists(self, key):
            if scenario == "store_failure":
                raise ConnectionError("revocation lookup unavailable")
            return int(scenario == "revoked")

    middleware = auth_middleware.SecureAuthMiddleware.__new__(
        auth_middleware.SecureAuthMiddleware
    )
    middleware.jwt_secret = "kp03-test-signing-key"
    middleware.jwt_algorithm = "HS256"
    middleware.redis_client = Store()
    tenant, user = str(uuid4()), str(uuid4())
    payload = {
        "sub": user, "tenant_id": "default" if scenario == "wrong_tenant" else tenant,
        "token_id": "" if scenario == "missing_token_id" else "kp03-session",
        "roles": ["admin"], "permissions": ["memory.write"],
        "iss": "ai-karen", "aud": "ai-karen-users",
        "exp": datetime.now(timezone.utc) + (
            timedelta(minutes=-1) if scenario == "expired" else timedelta(minutes=5)
        ),
    }
    key = "different-signing-key" if scenario == "tampered" else middleware.jwt_secret
    token = jwt.encode(payload, key, algorithm="HS256")
    monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
    monkeypatch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
    request = Request({
        "type": "http", "method": "POST", "path": "/internal",
        "headers": [(b"authorization", ("Bearer " + token).encode())],
        "query_string": b"",
    })
    if scenario == "valid":
        result = await migration_policy_request_from_authenticated_http(
            request=request, request_id="request-1", correlation_id="trace-1",
        )
        assert result.tenant_id == tenant and result.user_id == user
        assert result.action == "legacy_persona_memory_migration"
    else:
        with pytest.raises((PermissionError, ValueError)):
            await migration_policy_request_from_authenticated_http(
                request=request, request_id="request-1", correlation_id="trace-1",
            )


@pytest.mark.asyncio
async def test_authenticated_http_assembly_forwards_only_verified_policy(monkeypatch):
    from uuid import uuid4
    from starlette.requests import Request
    from ai_karen_engine.core.memory import legacy_persona_admission as module
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        LegacyMigrationReplayIdentity,
    )
    tenant, user = str(uuid4()), str(uuid4())
    verified = PolicyEvaluationRequest(
        tenant_id=tenant, user_id=user, session_id="verified-session",
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    observed = []
    async def authenticate(**kwargs):
        observed.append("authenticate")
        return verified
    async def assemble(**kwargs):
        observed.append("assemble")
        assert kwargs["request"] is verified
        assert kwargs["source_record_id"] == "legacy-source"
        return LegacyMigrationReplayIdentity(
            memory_id=str(uuid4()), request_id=str(uuid4()),
            source_record_id="legacy-source",
        )
    monkeypatch.setattr(module, "migration_policy_request_from_authenticated_http", authenticate)
    monkeypatch.setattr(module, "_prepare_governed_legacy_migration_from_policy_request", assemble)
    request = Request({
        "type": "http", "method": "POST", "path": "/internal",
        "headers": [], "query_string": b"",
    })
    result = await module.prepare_authenticated_http_legacy_migration_retry(
        request=request, request_id="req", correlation_id="trace",
        source_record_id="legacy-source", runtime_policy=RuntimePolicyEnforcer(),
    )
    assert result.source_record_id == "legacy-source"
    assert observed == ["authenticate", "assemble"]


@pytest.mark.asyncio
async def test_authenticated_http_assembly_never_reads_on_auth_failure(monkeypatch):
    from starlette.requests import Request
    from ai_karen_engine.core.memory import legacy_persona_admission as module
    from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer

    async def denied(**kwargs):
        raise PermissionError("revoked credential")
    async def unexpected(**kwargs):
        raise AssertionError("unauthenticated caller reached historical assembly")
    monkeypatch.setattr(module, "migration_policy_request_from_authenticated_http", denied)
    monkeypatch.setattr(module, "_prepare_governed_legacy_migration_from_policy_request", unexpected)
    request = Request({
        "type": "http", "method": "POST", "path": "/internal",
        "headers": [], "query_string": b"",
    })
    with pytest.raises(PermissionError, match="revoked credential"):
        await module.prepare_authenticated_http_legacy_migration_retry(
            request=request, request_id="req", correlation_id="trace",
            source_record_id="legacy-source", runtime_policy=RuntimePolicyEnforcer(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_flags", [
    {"memory_write_authorized": True},
    {"allowed_capabilities": ["memory.write"]},
    {"allowed_capabilities": ["*"]},
    {"memory_write_authorized": True, "migration_authorized": True,
     "policy_decision_id": "forged-decision"},
])
async def test_historical_vault_write_rejects_constructible_policy_flags_before_db(
    policy_flags,
):
    """No constructible context can open the disabled migration write path."""
    import uuid
    from ai_karen_engine.core.memory.protocols import VaultContext
    from ai_karen_engine.core.memory.types import (
        MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryType,
    )
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError, PostgresNeuroVault,
    )

    tenant, user = str(uuid.uuid4()), str(uuid.uuid4())

    def no_database_access():
        raise AssertionError("migration attempted a database operation")

    vault = PostgresNeuroVault(session_factory=no_database_access)
    entry = MemoryEntry(
        id=str(uuid.uuid4()), content="Never imported",
        memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
        metadata=MemoryMetadata(
            tenant_id=tenant, user_id=user, source="legacy_persona",
            custom={"consent_scope": "persona-memory-migration"},
        ),
    )
    context = VaultContext(
        tenant_id=tenant, user_id=user, request_id="request",
        correlation_id="trace", actor_id=user, policy_context=policy_flags,
    )
    with pytest.raises(NeuroVaultAuthorizationError):
        await vault.persist(entry, context=context)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,custom", [
    ("legacy_persona", {"consent_scope": "memory.write"}),
    ("chat_user", {"source_type": "legacy_persona", "consent_scope": "memory.write"}),
    ("legacy_persona", {}),
])
async def test_historical_source_cannot_bypass_disabled_writer_by_relabeling(
    source, custom,
):
    import uuid
    from ai_karen_engine.core.memory.protocols import VaultContext
    from ai_karen_engine.core.memory.types import (
        MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryType,
    )
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError, PostgresNeuroVault,
    )

    tenant, user = str(uuid.uuid4()), str(uuid.uuid4())

    def forbidden_session():
        raise AssertionError("historical source accessed database")

    entry = MemoryEntry(
        id=str(uuid.uuid4()), content="Historical import forbidden",
        memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
        metadata=MemoryMetadata(
            tenant_id=tenant, user_id=user, source=source, custom=custom,
        ),
    )
    context = VaultContext(
        tenant_id=tenant, user_id=user, request_id="req",
        correlation_id="corr", actor_id=user,
        policy_context={"memory_write_authorized": True},
    )
    with pytest.raises(
        NeuroVaultAuthorizationError, match="historical migration persistence is disabled",
    ):
        await PostgresNeuroVault(session_factory=forbidden_session).persist(
            entry, context=context,
        )

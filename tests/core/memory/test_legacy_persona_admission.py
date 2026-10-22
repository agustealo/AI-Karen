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

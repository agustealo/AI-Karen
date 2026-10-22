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

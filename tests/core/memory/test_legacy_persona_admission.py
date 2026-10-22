"""Migration preflight does not confer write authority."""
from ai_karen_engine.core.memory.legacy_persona_admission import (
    LegacyMigrationWriteAuthority, admit_legacy_migration,
    derive_legacy_migration_replay_identity,
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

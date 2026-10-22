"""Migration preflight does not confer write authority."""
from ai_karen_engine.core.memory.legacy_persona_admission import (
    LegacyMigrationWriteAuthority, admit_legacy_migration,
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

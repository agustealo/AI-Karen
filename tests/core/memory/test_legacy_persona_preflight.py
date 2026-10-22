"""Legacy migration preflight cannot infer authorization from legacy rows."""
from uuid import uuid4

from ai_karen_engine.core.memory.legacy_persona_preflight import (
    LegacyMigrationEvidence, preflight_legacy_memory,
)


def evidence(**overrides):
    tenant, user = str(uuid4()), str(uuid4())
    values = dict(
        legacy_tenant_id=tenant, authorized_tenant_id=tenant,
        legacy_user_id=user, authorized_user_id=user,
        identity_verified=False, consent_verified=False,
        retention_verified=False, source_record_verified=False,
        evidence_origin="authorized_runtime",
    )
    values.update(overrides)
    return LegacyMigrationEvidence(**values)


def test_unverified_evidence_cannot_authorize_migration():
    result = preflight_legacy_memory(evidence())
    assert not result.eligible
    assert set(result.reason_codes) == {
        "identity_unverified", "consent_unverified",
        "retention_unverified", "source_record_unverified",
    }


def test_verified_scope_is_only_preflight_not_a_write_grant():
    initial = evidence()
    result = preflight_legacy_memory(LegacyMigrationEvidence(
        **{**initial.__dict__, **{
            "identity_verified": True, "consent_verified": True,
            "retention_verified": True, "source_record_verified": True,
        }}
    ))
    assert result.eligible
    assert result.reason_codes == ()


def test_cross_tenant_or_user_scope_rejected():
    base = evidence(
        identity_verified=True, consent_verified=True,
        retention_verified=True, source_record_verified=True,
    )
    for field in ("authorized_tenant_id", "authorized_user_id"):
        result = preflight_legacy_memory(LegacyMigrationEvidence(
            **{**base.__dict__, field: str(uuid4())}
        ))
        assert not result.eligible
        assert "principal_mismatch" in result.reason_codes


def test_invalid_identity_rejected():
    assert preflight_legacy_memory(evidence(legacy_user_id="legacy-user")).reason_codes == (
        "invalid_identity_format",
    )


def test_untrusted_evidence_origin_blocks_forged_verified_flags():
    original = evidence(
        identity_verified=True, consent_verified=True,
        retention_verified=True, source_record_verified=True,
        evidence_origin="legacy_row",
    )
    result = preflight_legacy_memory(original)
    assert not result.eligible
    assert result.reason_codes == ("evidence_origin_untrusted",)

"""Recovery never treats an unverified or mismatched receipt as completion."""
from ai_karen_engine.core.memory.legacy_persona_recovery import (
    LegacyReplayReceiptEvidence, reconcile_legacy_replay, requires_fresh_migration_authorization,
)


def evidence(**overrides):
    values = dict(
        expected_memory_id="memory-1", expected_tenant_id="tenant-a",
        expected_user_id="user-a", persisted_memory_id=None,
        persisted_tenant_id=None, persisted_user_id=None, persisted=False,
    )
    values.update(overrides)
    return LegacyReplayReceiptEvidence(**values)


def test_missing_receipt_requires_reauthorization_before_retry():
    decision = reconcile_legacy_replay(evidence())
    assert decision.safe_to_retry and not decision.already_persisted
    assert decision.reason == "no_prior_receipt"


def test_matching_persisted_receipt_marks_completed():
    decision = reconcile_legacy_replay(evidence(
        persisted_memory_id="memory-1", persisted_tenant_id="tenant-a",
        persisted_user_id="user-a", persisted=True,
    ))
    assert decision.already_persisted and not decision.safe_to_retry


def test_mismatched_tenant_or_user_receipt_never_authorizes_replay():
    for field in ("persisted_tenant_id", "persisted_user_id"):
        values = dict(persisted_memory_id="memory-1", persisted_tenant_id="tenant-a",
                      persisted_user_id="user-a", persisted=True)
        values[field] = "untrusted"
        decision = reconcile_legacy_replay(evidence(**values))
        assert not decision.already_persisted and not decision.safe_to_retry
        assert decision.reason == "receipt_scope_mismatch"


def test_inconsistent_or_failed_receipt_needs_manual_reconciliation():
    for candidate in (
        evidence(persisted=True),
        evidence(persisted_memory_id="memory-1", persisted_tenant_id="tenant-a",
                 persisted_user_id="user-a", persisted=False),
    ):
        decision = reconcile_legacy_replay(candidate)
        assert not decision.already_persisted and not decision.safe_to_retry


def test_missing_receipt_only_triggers_fresh_authorization_not_write():
    candidate = reconcile_legacy_replay(evidence())
    assert requires_fresh_migration_authorization(candidate)
    completed = reconcile_legacy_replay(evidence(
        persisted_memory_id="memory-1", persisted_tenant_id="tenant-a",
        persisted_user_id="user-a", persisted=True,
    ))
    assert not requires_fresh_migration_authorization(completed)
    rejected = reconcile_legacy_replay(evidence(
        persisted_memory_id="memory-1", persisted_tenant_id="other",
        persisted_user_id="user-a", persisted=True,
    ))
    assert not requires_fresh_migration_authorization(rejected)

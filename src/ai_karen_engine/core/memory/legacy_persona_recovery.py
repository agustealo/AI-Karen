"""Pure reconciliation of durable NeuroVault receipts after interrupted migrations.

Read-only decision helper. The executor must retrieve receipt facts through the
canonical tenant/user-scoped ledger; this module never queries, mutates, or
grants permission to migrate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyReplayReceiptEvidence:
    expected_memory_id: str
    expected_tenant_id: str
    expected_user_id: str
    persisted_memory_id: str | None
    persisted_tenant_id: str | None
    persisted_user_id: str | None
    persisted: bool


@dataclass(frozen=True)
class LegacyReplayRecoveryDecision:
    already_persisted: bool
    safe_to_retry: bool
    reason: str


def reconcile_legacy_replay(evidence: LegacyReplayReceiptEvidence) -> LegacyReplayRecoveryDecision:
    """Never infer completed persistence from an ID alone."""
    if not all((evidence.expected_memory_id, evidence.expected_tenant_id, evidence.expected_user_id)):
        return LegacyReplayRecoveryDecision(False, False, "missing_expected_scope")
    if evidence.persisted_memory_id is None:
        if any((evidence.persisted_tenant_id, evidence.persisted_user_id, evidence.persisted)):
            return LegacyReplayRecoveryDecision(False, False, "inconsistent_receipt")
        return LegacyReplayRecoveryDecision(False, True, "no_prior_receipt")
    if (
        evidence.persisted_memory_id != evidence.expected_memory_id
        or evidence.persisted_tenant_id != evidence.expected_tenant_id
        or evidence.persisted_user_id != evidence.expected_user_id
    ):
        return LegacyReplayRecoveryDecision(False, False, "receipt_scope_mismatch")
    if not evidence.persisted:
        return LegacyReplayRecoveryDecision(False, False, "receipt_not_persisted")
    return LegacyReplayRecoveryDecision(True, False, "already_persisted")

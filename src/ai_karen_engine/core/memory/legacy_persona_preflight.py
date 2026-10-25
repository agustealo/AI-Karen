"""Fail-closed preflight for a single legacy persona-memory record.

Pure validation only. This module never queries personal content, grants consent,
constructs a VaultContext, or writes to NeuroVault. Identity and permission
facts must come from separately verified authoritative sources.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyMigrationEvidence:
    legacy_tenant_id: str
    legacy_user_id: str
    authorized_tenant_id: str
    authorized_user_id: str
    identity_verified: bool
    consent_verified: bool
    retention_verified: bool
    source_record_verified: bool
    evidence_origin: str = "unverified"


@dataclass(frozen=True)
class LegacyMigrationPreflight:
    eligible: bool
    reason_codes: tuple[str, ...]


def preflight_legacy_memory(evidence: LegacyMigrationEvidence) -> LegacyMigrationPreflight:
    reasons: list[str] = []
    try:
        legacy_tenant = uuid.UUID(evidence.legacy_tenant_id)
        approved_tenant = uuid.UUID(evidence.authorized_tenant_id)
        legacy_user = uuid.UUID(evidence.legacy_user_id)
        approved_user = uuid.UUID(evidence.authorized_user_id)
    except (TypeError, AttributeError, ValueError):
        return LegacyMigrationPreflight(False, ("invalid_identity_format",))

    if evidence.evidence_origin != "authorized_runtime":
        reasons.append("evidence_origin_untrusted")
    if legacy_tenant != approved_tenant or legacy_user != approved_user:
        reasons.append("principal_mismatch")
    if not evidence.identity_verified:
        reasons.append("identity_unverified")
    if not evidence.consent_verified:
        reasons.append("consent_unverified")
    if not evidence.retention_verified:
        reasons.append("retention_unverified")
    if not evidence.source_record_verified:
        reasons.append("source_record_unverified")
    return LegacyMigrationPreflight(not reasons, tuple(reasons))

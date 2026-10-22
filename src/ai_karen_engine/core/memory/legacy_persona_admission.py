"""Migration admission gate; never a substitute for NeuroVault authorization.

The caller must obtain fresh, trusted runtime policy independently. This pure
gate rejects mismatched, denied or unverified policy evidence before any writer
is even considered. NeuroVault remains the final enforcement authority.
"""
from __future__ import annotations

from dataclasses import dataclass

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
    return LegacyMigrationAdmission(not reasons, tuple(reasons))

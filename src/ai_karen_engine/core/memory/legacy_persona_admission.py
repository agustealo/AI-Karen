"""Migration admission gate; never a substitute for NeuroVault authorization.

The caller must obtain fresh, trusted runtime policy independently. This pure
gate rejects mismatched, denied or unverified policy evidence before any writer
is even considered. NeuroVault remains the final enforcement authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import uuid

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
    tenant_id: str | None = None
    user_id: str | None = None


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
    return LegacyMigrationAdmission(
        not reasons, tuple(reasons),
        tenant_id=authority.tenant_id if not reasons else None,
        user_id=authority.user_id if not reasons else None,
    )


@dataclass(frozen=True)
class LegacyMigrationReplayIdentity:
    """Stable retry identifiers, not an authorization or migration receipt."""

    memory_id: str
    request_id: str
    source_record_id: str


def derive_legacy_migration_replay_identity(
    *,
    admission: LegacyMigrationAdmission,
    tenant_id: str,
    user_id: str,
    source_record_id: str,
) -> LegacyMigrationReplayIdentity:
    """Produce stable identifiers for NeuroVault's entry+request idempotency.

    The executor must independently verify admission scope and current consent.
    """
    if not admission.admitted or admission.reason_codes:
        raise ValueError("legacy migration admission required")
    try:
        tenant = uuid.UUID(tenant_id)
        user = uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("canonical UUID migration identities required") from exc
    if admission.tenant_id != str(tenant) or admission.user_id != str(user):
        raise ValueError("migration principal does not match admitted scope")
    source = str(source_record_id or "").strip()
    if not source or len(source) > 255:
        raise ValueError("bounded source record identifier required")
    stable = f"ai-karen:persona-memory:v1:{tenant}:{user}:{source}"
    return LegacyMigrationReplayIdentity(
        memory_id=str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ":memory")),
        request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, stable + ":request")),
        source_record_id=source,
    )

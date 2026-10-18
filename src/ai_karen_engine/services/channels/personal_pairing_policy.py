"""Fail-closed policy contract for optional unofficial personal-account pairing.

This is NOT a WhatsApp Web client and NEVER generates pairing credentials.
Only the existing governed ChannelHost may execute an enabled transport,
after persisted consent has been verified by its canonical service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final


PERSONAL_WHATSAPP_CONSENT_VERSION: Final[str] = "whatsapp-personal-risk-v1"


class PersonalPairingState(StrEnum):
    UNAVAILABLE = "unavailable"
    CONSENT_REQUIRED = "consent_required"
    READY_TO_PAIR = "ready_to_pair"
    PAIRING = "pairing"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class PersonalPairingConsent:
    """Persisted server-issued evidence, not a browser checkbox or native event."""

    tenant_id: str
    user_id: str
    connection_id: str
    provider_id: str
    policy_version: str
    accepted_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PersonalPairingAssessment:
    state: PersonalPairingState
    can_create_session: bool
    reason: str


def assess_personal_pairing(
    *,
    tenant_id: str,
    user_id: str,
    connection_id: str,
    provider_id: str,
    provider_vetted: bool,
    provider_enabled: bool,
    authorized_by_runtime_policy: bool,
    consent: PersonalPairingConsent | None,
    now: datetime,
) -> PersonalPairingAssessment:
    """Evaluate prerequisites before any external session/QR generation.

    The caller MUST resolve persisted consent under tenant RLS and must recheck
    RuntimePolicy immediately before an external provider action. The result
    is an admission decision only, never a side-effect authorization token.
    """
    if any(not isinstance(value, str) or not value.strip() for value in
           (tenant_id, user_id, connection_id, provider_id)):
        raise ValueError("Personal pairing requires exact nonempty scope")
    if now.tzinfo is None:
        raise ValueError("Timezone-aware server time required")
    if not provider_vetted or not provider_enabled:
        return PersonalPairingAssessment(
            PersonalPairingState.UNAVAILABLE, False,
            "No approved managed personal-account connector is available",
        )
    if not authorized_by_runtime_policy:
        return PersonalPairingAssessment(
            PersonalPairingState.UNAVAILABLE, False,
            "Channel pairing is not authorized",
        )
    if consent is None:
        return PersonalPairingAssessment(
            PersonalPairingState.CONSENT_REQUIRED, False,
            "Explicit risk acknowledgement is required",
        )
    if (
        consent.tenant_id != tenant_id
        or consent.user_id != user_id
        or consent.connection_id != connection_id
        or consent.provider_id != provider_id
        or consent.policy_version != PERSONAL_WHATSAPP_CONSENT_VERSION
        or consent.revoked_at is not None
        or consent.accepted_at.tzinfo is None
        or consent.accepted_at > now
    ):
        return PersonalPairingAssessment(
            PersonalPairingState.CONSENT_REQUIRED, False,
            "Consent is absent, revoked, outdated or belongs to another scope",
        )
    return PersonalPairingAssessment(
        PersonalPairingState.READY_TO_PAIR, True,
        "Current scoped consent and provider admission prerequisites verified",
    )


__all__ = [
    "PERSONAL_WHATSAPP_CONSENT_VERSION",
    "PersonalPairingAssessment",
    "PersonalPairingConsent",
    "PersonalPairingState",
    "assess_personal_pairing",
]

"""Authenticated managed-provider callback envelope, without transport execution.

This is a narrow optional integration contract, NOT an official WhatsApp API.
Only trusted ChannelHost callers may invoke the decoder with a signing secret
resolved by the canonical per-tenant CredentialVault. No provider is configured
by default. This module cannot create QR codes, sessions, or external effects.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Mapping

from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
    PairingEvent,
    PairingEvidenceDenied,
    PairingObservation,
)


_MAX_CALLBACK_BYTES = 16_384
_MAX_CLOCK_SKEW_SECONDS = 300
_REQUIRED = frozenset({
    "tenant_id", "connection_id", "provider_id", "connection_revision",
    "sequence", "event", "observed_at", "provider_receipt_id", "qr_expires_at",
})


def _unique_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in items:
        if key in obj:
            raise PairingEvidenceDenied("Duplicate callback field")
        obj[key] = value
    return obj


def verify_personal_pairing_callback(
    *,
    body: bytes,
    headers: Mapping[str, str],
    signing_secret: str,
    tenant_id: str,
    connection_id: str,
    provider_id: str,
    now: datetime,
) -> PairingObservation:
    """Verify HMAC over exact bytes before parsing any untrusted event data.

    A vetted provider must explicitly implement this documented
    X-Karen-Pairing-Signature: sha256=<hex> integration contract.
    A signing key proves only possession of the configured secret. The host
    must independently validate the active installation, vault handle, owner
    and provider configuration, and SQL must fence sequence and revision.
    """
    if (
        type(body) is not bytes
        or not 1 <= len(body) <= _MAX_CALLBACK_BYTES
        or not isinstance(signing_secret, str)
        or len(signing_secret.encode("utf-8")) < 32
        or now.tzinfo is None
    ):
        raise PairingEvidenceDenied("Invalid signed callback prerequisites")
    signatures = [
        value for key, value in headers.items()
        if key.lower() == "x-karen-pairing-signature"
    ]
    if len(signatures) != 1:
        raise PairingEvidenceDenied("Exactly one callback signature required")
    signature = signatures[0]
    if not isinstance(signature, str) or len(signature) != 71 or not signature.startswith("sha256="):
        raise PairingEvidenceDenied("Signed callback required")
    sig_hex = signature[7:]
    if any(c not in "0123456789abcdef" for c in sig_hex):
        raise PairingEvidenceDenied("Invalid callback signature format")
    expected = hmac.new(
        signing_secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_hex):
        raise PairingEvidenceDenied("Callback signature mismatch")
    try:
        parsed = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PairingEvidenceDenied("Invalid callback JSON") from exc
    if not isinstance(parsed, dict) or parsed.keys() != _REQUIRED:
        raise PairingEvidenceDenied("Unexpected callback fields")
    if (
        any(type(parsed[key]) is not str for key in ("tenant_id", "connection_id", "provider_id", "event", "observed_at"))
        or type(parsed["connection_revision"]) is not int
        or type(parsed["sequence"]) is not int
        or type(parsed["provider_receipt_id"]) not in (str, type(None))
        or type(parsed["qr_expires_at"]) not in (str, type(None))
        or (parsed["tenant_id"], parsed["connection_id"], parsed["provider_id"])
        != (tenant_id, connection_id, provider_id)
    ):
        raise PairingEvidenceDenied("Callback identity or types rejected")
    try:
        observed_at = datetime.fromisoformat(parsed["observed_at"].replace("Z", "+00:00"))
        qr_expires_at = (
            datetime.fromisoformat(parsed["qr_expires_at"].replace("Z", "+00:00"))
            if parsed["qr_expires_at"] else None
        )
        event = PairingEvent(parsed["event"])
    except ValueError as exc:
        raise PairingEvidenceDenied("Invalid callback timestamp or event") from exc
    if (
        observed_at.tzinfo is None
        or (qr_expires_at is not None and qr_expires_at.tzinfo is None)
        or abs((now - observed_at).total_seconds()) > _MAX_CLOCK_SKEW_SECONDS
        or parsed["connection_revision"] < 1
        or parsed["sequence"] < 1
        or (parsed["provider_receipt_id"] is not None
            and not 1 <= len(parsed["provider_receipt_id"]) <= 256)
    ):
        raise PairingEvidenceDenied("Expired or invalid callback evidence")
    return PairingObservation(
        tenant_id=tenant_id,
        connection_id=connection_id,
        provider_id=provider_id,
        connection_revision=parsed["connection_revision"],
        sequence=parsed["sequence"],
        event=event,
        observed_at=observed_at,
        authenticated=True,
        provider_receipt_id=parsed["provider_receipt_id"],
        qr_expires_at=qr_expires_at,
    )


__all__ = ["verify_personal_pairing_callback"]

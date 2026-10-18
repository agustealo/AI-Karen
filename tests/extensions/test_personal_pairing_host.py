"""Host must source managed callback authority from registry + Vault, not payload."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
    PairingEvidenceDenied, PairingPhase, PairingSnapshot,
)
from tests.extensions.test_channel_host_lifecycle import fake_components

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONNECTION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
KEY = "a-real-vault-key-with-at-least-thirty-two-characters"


def signed():
    now = datetime.now(timezone.utc)
    body = json.dumps({
        "tenant_id": TENANT, "connection_id": CONNECTION,
        "provider_id": "managed-operator",
        "connection_revision": 1, "sequence": 1, "event": "qr_issued",
        "observed_at": now.isoformat(),
        "provider_receipt_id": None,
        "qr_expires_at": (now + timedelta(seconds=90)).isoformat(),
    }, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(KEY.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Karen-Pairing-Signature": signature}


@pytest.mark.asyncio
async def test_host_rejects_signed_provider_when_no_operator_is_vetted():
    host, _, _, _, adapter = fake_components()
    await host.initialize()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://reference", revision=1, enabled=False,
    ))
    host.repository.commit_personal_pairing_observation = AsyncMock()
    body, headers = signed()
    with pytest.raises(PairingEvidenceDenied, match="vetted"):
        await host.admit_signed_personal_pairing_event(
            tenant_id=TENANT, connection_id=CONNECTION,
            headers=headers, body=body,
        )
    host.repository.commit_personal_pairing_observation.assert_not_awaited()
    adapter.start.assert_not_awaited()
    await host.shutdown()


@pytest.mark.asyncio
async def test_only_real_vault_verified_callback_can_reach_durable_repository():
    host, _, _, _, adapter = fake_components()
    await host.initialize()
    host.settings = replace(
        host.settings,
        installations={
            "telegram-bot": frozenset({
                "bot_token", "webhook_secret", "pairing_webhook_secret",
            }),
        },
        personal_pairing_providers={"telegram-bot": "managed-operator"},
    ).validate()
    host.repository.get_connection = AsyncMock(return_value=ChannelConnection(
        connection_id=CONNECTION, tenant_id=TENANT,
        installation_id="telegram-bot", provider_account_id="account",
        credential_handle="vault://reference", revision=1, enabled=False,
    ))
    host.repository.get_personal_connection_owner = AsyncMock(return_value=USER)
    host._resolvers["telegram-bot"] = AsyncMock(return_value={
        "pairing_webhook_secret": KEY,
    })
    result = PairingSnapshot(
        tenant_id=TENANT, connection_id=CONNECTION,
        provider_id="managed-operator", connection_revision=1,
        sequence=1, phase=PairingPhase.QR_AVAILABLE,
    )
    host.repository.commit_personal_pairing_observation = AsyncMock(return_value=result)
    body, headers = signed()
    bad = dict(headers)
    bad["X-Karen-Pairing-Signature"] = "sha256=" + "0" * 64
    with pytest.raises(PairingEvidenceDenied):
        await host.admit_signed_personal_pairing_event(
            tenant_id=TENANT, connection_id=CONNECTION,
            headers=bad, body=body,
        )
    host.repository.commit_personal_pairing_observation.assert_not_awaited()
    response = await host.admit_signed_personal_pairing_event(
        tenant_id=TENANT, connection_id=CONNECTION,
        headers=headers, body=body,
    )
    assert response is result
    host.repository.commit_personal_pairing_observation.assert_awaited_once()
    kwargs = host.repository.commit_personal_pairing_observation.await_args.kwargs
    assert kwargs["user_id"] == USER
    assert kwargs["observation"].authenticated is True
    assert kwargs["provider_vetted_and_enabled"] is True
    host._resolvers["telegram-bot"].assert_awaited_with(
        tenant_id=TENANT, credential_handle="vault://reference",
    )
    adapter.start.assert_not_awaited()
    await host.shutdown()

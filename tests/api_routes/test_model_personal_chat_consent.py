"""Authenticated personal-model consent storage is not runtime authorization."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ai_karen_engine.api_routes.models import settings as model_settings


def _request() -> Request:
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/settings/model/credentials/consent",
        "headers": [],
    })
    request.state.correlation_id = "model-consent-correlation"
    return request


@pytest.mark.asyncio
async def test_owner_can_store_consent_without_runtime_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.uuid4()
    credential_id = uuid.uuid4()
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(
        model_settings, "get_credential_vault_service",
        lambda: SimpleNamespace(set_owned_personal_model_chat_consent=write),
    )
    result = await model_settings.set_consumer_model_chat_consent(
        credential_id,
        model_settings.ConsumerModelChatConsentRequest(
            enabled=True, model_id="gpt-4o-mini",
        ),
        _request(),
        current_user={"user_id": "alice", "tenant_id": str(tenant)},
    )
    assert result.credential_id == credential_id
    assert result.consent_enabled is True
    assert result.model_id == "gpt-4o-mini"
    assert result.runtime_authorized is False
    write.assert_awaited_once_with(
        credential_id=credential_id,
        tenant_id=tenant,
        user_id="alice",
        model_id="gpt-4o-mini",
        enabled=True,
        correlation_id="model-consent-correlation",
    )
    assert "api_key" not in result.model_dump()


@pytest.mark.asyncio
async def test_owner_can_withdraw_consent_without_model_or_provider_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.uuid4()
    credential_id = uuid.uuid4()
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(
        model_settings, "get_credential_vault_service",
        lambda: SimpleNamespace(set_owned_personal_model_chat_consent=write),
    )
    result = await model_settings.set_consumer_model_chat_consent(
        credential_id,
        model_settings.ConsumerModelChatConsentRequest(enabled=False),
        _request(),
        current_user={"user_id": "alice", "tenant_id": str(tenant)},
    )
    assert result.consent_enabled is False
    assert result.model_id is None
    assert result.runtime_authorized is False
    assert write.await_args.kwargs["enabled"] is False
    assert write.await_args.kwargs["model_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor", "model_id", "expected_code"),
    [
        ({"user_id": "", "tenant_id": str(uuid.uuid4())}, "gpt-4o-mini", 403),
        ({"user_id": "alice", "tenant_id": ""}, "gpt-4o-mini", 403),
        ({"user_id": "alice", "tenant_id": str(uuid.uuid4())}, "", 422),
        ({"user_id": "alice", "tenant_id": str(uuid.uuid4())}, " auto", 422),
    ],
)
async def test_invalid_owner_or_explicit_selection_never_reaches_vault(
    monkeypatch: pytest.MonkeyPatch,
    actor: dict[str, str],
    model_id: str,
    expected_code: int,
) -> None:
    write = AsyncMock()
    monkeypatch.setattr(
        model_settings, "get_credential_vault_service",
        lambda: SimpleNamespace(set_owned_personal_model_chat_consent=write),
    )
    with pytest.raises(HTTPException) as exc:
        await model_settings.set_consumer_model_chat_consent(
            uuid.uuid4(),
            model_settings.ConsumerModelChatConsentRequest(
                enabled=True, model_id=model_id,
            ),
            _request(),
            current_user=actor,
        )
    assert exc.value.status_code == expected_code
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (False, 404),
        (ValueError("invalid model choice"), 422),
        (PermissionError("model unavailable"), 409),
        (RuntimeError("audit storage offline"), 503),
    ],
)
async def test_consumer_consent_never_claims_uncommitted_or_denied_save(
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
    expected_code: int,
) -> None:
    tenant = uuid.uuid4()
    write = AsyncMock(side_effect=outcome if isinstance(outcome, Exception) else None)
    if outcome is False:
        write.return_value = False
    monkeypatch.setattr(
        model_settings, "get_credential_vault_service",
        lambda: SimpleNamespace(set_owned_personal_model_chat_consent=write),
    )
    with pytest.raises(HTTPException) as exc:
        await model_settings.set_consumer_model_chat_consent(
            uuid.uuid4(),
            model_settings.ConsumerModelChatConsentRequest(
                enabled=True, model_id="gpt-4o-mini",
            ),
            _request(),
            current_user={"user_id": "alice", "tenant_id": str(tenant)},
        )
    assert exc.value.status_code == expected_code

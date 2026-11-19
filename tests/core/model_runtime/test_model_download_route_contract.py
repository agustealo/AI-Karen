from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.models import model_orchestrator as setup_api

from ai_karen_engine.api_routes.models.model_orchestrator import (
    ModelDownloadRequest,
    _model_dump,
)


def test_model_download_request_serializes_reviewed_revision() -> None:
    request = ModelDownloadRequest(
        model_id="test-owner/test-model",
        revision=None,
        validated_revision="reviewed-sha",
        accept_license=True,
    )

    payload = _model_dump(request)

    assert payload["validated_revision"] == "reviewed-sha"
    assert payload["revision"] is None
    assert payload["accept_license"] is True


from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    E_COMPAT,
    E_NET,
    E_NOT_FOUND,
    E_PERM,
    ModelOrchestratorError,
)


def test_recommended_model_failure_diagnostics_are_actionable_and_redacted() -> None:
    cases = (
        (E_COMPAT, "huggingface_hub"),
        (E_NET, "DNS"),
        (E_NOT_FOUND, "model ID"),
        (E_PERM, "credentials"),
    )
    for code, expected in cases:
        error = ModelOrchestratorError(
            code, "private failure", {"token": "do-not-expose"}
        )
        message = ModelDownloadControlService._recommendation_verification_error(
            error, "remote_model_metadata"
        )
        assert expected in message
        assert "do-not-expose" not in message
        assert "private failure" not in message


def test_recommended_model_missing_metadata_still_fails_closed() -> None:
    error = RuntimeError("untrusted source error with secret")
    message = ModelDownloadControlService._recommendation_verification_error(
        error, "remote_model_metadata"
    )
    assert "secret" not in message
    assert "connectivity" in message


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["recommendations", "policy", "channels"])
async def test_setup_read_service_outage_returns_redacted_503(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    secret = "private-model-backend-credential"
    failure = RuntimeError(secret)
    service = SimpleNamespace(
        get_recommendations=AsyncMock(side_effect=failure),
        get_policy=AsyncMock(side_effect=failure),
        get_channels=AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(setup_api, "_control_service", lambda: service)
    endpoints = {
        "recommendations": lambda: setup_api.get_download_recommendations(
            current_user={"tenant_id": "11111111-1111-4111-8111-111111111111"}
        ),
        "policy": lambda: setup_api.get_download_policy(current_user={}),
        "channels": lambda: setup_api.get_download_channels(current_user={}),
    }
    with pytest.raises(HTTPException) as captured:
        await endpoints[resource]()
    assert captured.value.status_code == 503
    assert "temporarily unavailable" in str(captured.value.detail)
    assert secret not in str(captured.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["recommendations", "policy", "channels"])
async def test_setup_read_preserves_existing_http_denials(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    denied = HTTPException(status_code=403, detail="Access denied")
    service = SimpleNamespace(
        get_recommendations=AsyncMock(side_effect=denied),
        get_policy=AsyncMock(side_effect=denied),
        get_channels=AsyncMock(side_effect=denied),
    )
    monkeypatch.setattr(setup_api, "_control_service", lambda: service)
    endpoints = {
        "recommendations": lambda: setup_api.get_download_recommendations(
            current_user={"tenant_id": "11111111-1111-4111-8111-111111111111"}
        ),
        "policy": lambda: setup_api.get_download_policy(current_user={}),
        "channels": lambda: setup_api.get_download_channels(current_user={}),
    }
    with pytest.raises(HTTPException) as captured:
        await endpoints[resource]()
    assert captured.value.status_code == 403


@pytest.mark.asyncio
async def test_setup_policy_success_keeps_response_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "master_enabled": True,
        "core_runtime_enabled": True,
        "plugin_channels_enabled": True,
        "image_channels_enabled": True,
        "audio_channels_enabled": True,
        "vision_channels_enabled": True,
        "gguf_external_enabled": False,
        "trust_remote_code": False,
        "block_new_downloads": False,
        "pause_active_downloads": False,
        "quarantine_failed_models": True,
        "require_license_acceptance": True,
        "max_concurrent_downloads": 2,
    }
    service = SimpleNamespace(get_policy=AsyncMock(return_value=payload))
    monkeypatch.setattr(setup_api, "_control_service", lambda: service)
    result = await setup_api.get_download_policy(current_user={})
    assert result.master_enabled is True
    assert result.max_concurrent_downloads == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["recommendations", "policy", "channels"])
async def test_setup_domain_errors_keep_status_but_redact_private_details(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
        E_NET,
        ModelOrchestratorError,
    )

    secret = "private-source-access-token"
    failure = ModelOrchestratorError(
        E_NET, secret, {"credential": secret}
    )
    service = SimpleNamespace(
        get_recommendations=AsyncMock(side_effect=failure),
        get_policy=AsyncMock(side_effect=failure),
        get_channels=AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(setup_api, "_control_service", lambda: service)
    endpoints = {
        "recommendations": lambda: setup_api.get_download_recommendations(
            current_user={"tenant_id": "11111111-1111-4111-8111-111111111111"}
        ),
        "policy": lambda: setup_api.get_download_policy(current_user={}),
        "channels": lambda: setup_api.get_download_channels(current_user={}),
    }
    with pytest.raises(HTTPException) as captured:
        await endpoints[resource]()
    assert captured.value.status_code == 503
    assert secret not in str(captured.value.detail)
    assert isinstance(captured.value.detail, str)

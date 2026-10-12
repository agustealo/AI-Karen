from __future__ import annotations

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
    assert "unreachable" in message


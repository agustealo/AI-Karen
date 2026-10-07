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

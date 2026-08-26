from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.models.unavailable_capabilities import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_removed_conversion_and_quantization_fail_honestly() -> None:
    client = _client()

    cases = (
        ("/api/models/local/convert-to-gguf", "model_conversion"),
        ("/api/models/local/convert-to-gguf/validate", "model_conversion"),
        ("/api/models/local/quantize", "model_quantization"),
        ("/api/models/local/quantize/validate", "model_quantization"),
    )

    for path, capability in cases:
        response = client.post(path, json={})
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "MODEL_CAPABILITY_UNAVAILABLE"
        assert detail["capability"] == capability
        assert detail["degraded_mode"] is True
        assert detail["response_source"] == "capability_status"
        assert "legacy internal GGUF toolchain was removed" in detail["message"]


def test_format_contract_does_not_advertise_removed_internal_provider() -> None:
    client = _client()

    response = client.get("/api/models/local/formats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversion_available"] is False
    assert payload["quantization_available"] is False
    assert payload["response_source"] == "capability_status"

    gguf = payload["supported_formats"]["gguf"]
    assert gguf["internal_provider"] is False
    assert gguf["runtime_ownership"] == "external_openai_compatible"
    assert "local_gguf" not in str(payload)

from ai_karen_engine.core.runtime.runtime_attempt import RuntimeAttempt
from ai_karen_engine.core.runtime.runtime_metadata import RuntimeMetadata


def test_runtime_metadata_core_response() -> None:
    metadata = RuntimeMetadata(
        requested_target="core:transformers",
        resolved_target="core:transformers",
        execution_layer="core",
        response_source="core_runtime",
        runtime_engine="transformers",
        requested_model="gpt2",
        actual_model="gpt2",
        latency_ms=44.0,
        correlation_id="corr-1",
    )

    public = metadata.to_public_dict()

    assert public["runtime_engine"] == "transformers"
    assert public["provider_id"] is None
    assert public["response_source"] == "core_runtime"
    assert public["degraded_mode"] is False


def test_runtime_metadata_provider_fallback_response() -> None:
    first = RuntimeAttempt(
        target="provider:gemini",
        status="failed",
        execution_layer="provider",
        provider_id="gemini",
        error_type="provider_unavailable",
    )
    second = RuntimeAttempt(
        target="provider:ollama",
        status="success",
        execution_layer="provider",
        provider_id="ollama",
        actual_model="llama3.1",
    )

    metadata = RuntimeMetadata(
        requested_target="provider:gemini",
        resolved_target="provider:ollama",
        execution_layer="provider",
        response_source="fallback_provider_runtime",
        provider_id="ollama",
        actual_model="llama3.1",
        fallback_level=1,
        degraded_mode=True,
        degradation_type="provider_unavailable",
        degradation_reason="Gemini unavailable; Ollama generated the response.",
        attempts=(first, second),
    )

    public = metadata.to_public_dict()

    assert public["fallback_level"] == 1
    assert public["degraded_mode"] is True
    assert len(public["attempts"]) == 2
    assert public["attempts"][0]["status"] == "failed"
    assert public["attempts"][1]["status"] == "success"


def test_runtime_metadata_emergency_response() -> None:
    metadata = RuntimeMetadata(
        requested_target="core:transformers",
        resolved_target=None,
        execution_layer="emergency",
        response_source="emergency_static",
        fallback_level=99,
        degraded_mode=True,
        degradation_type="fallback_exhausted",
        degradation_reason="No runtime could generate a response.",
    )

    assert metadata.provider_id is None
    assert metadata.runtime_engine is None
    assert metadata.response_source == "emergency_static"

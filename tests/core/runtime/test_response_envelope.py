from ai_karen_engine.core.runtime.response_envelope import RuntimeResponseEnvelope
from ai_karen_engine.core.runtime.runtime_metadata import RuntimeMetadata


def test_response_envelope_public_dict() -> None:
    metadata = RuntimeMetadata(
        requested_target="core:transformers",
        resolved_target="core:transformers",
        execution_layer="core",
        response_source="core_runtime",
        runtime_engine="transformers",
        actual_model="gpt2",
    )

    envelope = RuntimeResponseEnvelope(
        output="hello",
        metadata=metadata,
    )

    public = envelope.to_public_dict()

    assert public["output"] == "hello"
    assert public["metadata"]["runtime_engine"] == "transformers"
    assert public["metadata"]["response_source"] == "core_runtime"
    assert public["warnings"] == []
    assert public["errors"] == []


def test_response_envelope_degraded_property() -> None:
    metadata = RuntimeMetadata(
        requested_target="provider:gemini",
        resolved_target=None,
        execution_layer="emergency",
        response_source="emergency_static",
        fallback_level=99,
        degraded_mode=True,
        degradation_type="fallback_exhausted",
    )

    envelope = RuntimeResponseEnvelope(
        output="System unavailable.",
        metadata=metadata,
    )

    assert envelope.degraded is True
    assert envelope.response_source == "emergency_static"

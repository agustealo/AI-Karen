from ai_karen_engine.core.runtime.runtime_attempt import RuntimeAttempt


def test_runtime_attempt_supports_core_runtime() -> None:
    attempt = RuntimeAttempt(
        target="core:transformers",
        status="success",
        execution_layer="core",
        runtime_engine="transformers",
        requested_model="gpt2",
        actual_model="gpt2",
        latency_ms=12.5,
    )

    assert attempt.provider_id is None
    assert attempt.runtime_engine == "transformers"
    assert attempt.status == "success"


def test_runtime_attempt_supports_provider_runtime() -> None:
    attempt = RuntimeAttempt(
        target="provider:gemini",
        status="failed",
        execution_layer="provider",
        provider_id="gemini",
        requested_model="gemini-2.5-flash",
        error_type="provider_unavailable",
        error_message="Provider health check failed.",
    )

    assert attempt.runtime_engine is None
    assert attempt.provider_id == "gemini"
    assert attempt.status == "failed"

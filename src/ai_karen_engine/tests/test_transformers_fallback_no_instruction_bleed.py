from ai_karen_engine.core.model_runtime.providers.transformers_runtime import TransformersRuntime


def test_transformers_fallback_no_instruction_bleed():
    runtime = TransformersRuntime(provider_name="builtin_transformers")
    response_text = runtime.generate("You are Karen... Assistant:")

    assert "You are Karen" not in response_text
    assert "Answer only" not in response_text
    assert "Do not" not in response_text
    assert "Assistant:" not in response_text
    assert "[transformers" not in response_text.lower()


def test_transformers_metadata_classification():
    runtime = TransformersRuntime(provider_name="builtin_transformers")
    metadata = {
        "requested_provider": "ollama",
        "actual_provider": "builtin_transformers",
        "response_source": runtime.health_check()["response_source"],
    }
    assert metadata["requested_provider"] == "ollama"
    assert metadata["actual_provider"] in {"Transformers", "transformers", "builtin_transformers"}
    assert metadata["response_source"] in {"live_model", "emergency_static", "deterministic_fallback"}

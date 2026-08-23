from ai_karen_engine.core.model_runtime.routing.llm_router_service import ProviderProcessingError


def test_provider_processing_error_accepts_error_list():
    err = ProviderProcessingError("ollama", [RuntimeError("boom")])
    assert "ollama failed after" in str(err)
    assert err.last_error is not None


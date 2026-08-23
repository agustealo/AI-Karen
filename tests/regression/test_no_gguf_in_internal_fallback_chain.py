from ai_karen_engine.core.model_runtime.routing.llm_router_service import ALLOWED_LIVE_FALLBACK_PROVIDERS


def test_no_gguf_in_internal_fallback_chain():
    blocked = {"local_gguf", "gguf", "llama_cpp", "llama.cpp", "llamacpp"}
    normalized = {x.lower().replace('-', '_').replace(' ', '_') for x in ALLOWED_LIVE_FALLBACK_PROVIDERS}
    assert blocked.isdisjoint(normalized)


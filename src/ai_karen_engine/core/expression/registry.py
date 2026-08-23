from __future__ import annotations
from .engines import BuiltinProviderEngine, DisabledEngine, OpenAICompatibleEngine
from ..model_runtime.provider_policy import evaluate_provider_policy


def get_engine(engine_id: str, engine_type: str | None = None):
    """
    Resolves an expression engine based on ID or type.
    Supports canonical engine categories (builtin, local, cloud) 
    and specific provider IDs (ollama, gemini, etc).
    """
    
    # 1. Map explicit engine type strings to their implementation classes
    by_type = {
        "builtin_provider_engine": BuiltinProviderEngine(),
        "openai_compatible": OpenAICompatibleEngine(),
        "disabled_engine": DisabledEngine(),
    }
    
    if engine_type and engine_type in by_type:
        engine = by_type[engine_type]
        engine.engine_id = engine_id
        return engine

    # 2. Resolve based on ID using provider taxonomy
    # This allows any configured provider to act as a logic engine
    decision = evaluate_provider_policy(engine_id)
    
    if decision.classification == "builtin_engine" or engine_id == "builtin":
        return BuiltinProviderEngine()
        
    if decision.classification in ("local_openai_endpoint", "cloud_provider") or engine_id in ("local", "cloud"):
        engine = OpenAICompatibleEngine()
        engine.engine_id = engine_id
        return engine
        
    # Default to disabled
    return DisabledEngine()

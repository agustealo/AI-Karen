from __future__ import annotations

from .engines import DisabledEngine, OpenAICompatibleEngine
from ..model_runtime.provider_policy import evaluate_provider_policy


def get_engine(engine_id: str, engine_type: str | None = None):
    """Resolve a canonical expression engine.

    Chat execution is provider-agnostic. Local and cloud providers both use the
    OpenAI-compatible engine surface; specialized Core ML runtimes are not a
    parallel chat-provider authority.
    """
    by_type = {
        "openai_compatible": OpenAICompatibleEngine(),
        "disabled_engine": DisabledEngine(),
    }

    if engine_type and engine_type in by_type:
        engine = by_type[engine_type]
        engine.engine_id = engine_id
        return engine

    normalized_engine_id = "local" if engine_id == "builtin" else engine_id
    decision = evaluate_provider_policy(normalized_engine_id)

    if decision.classification in {"local_openai_endpoint", "cloud_provider"} or normalized_engine_id in {
        "local",
        "cloud",
    }:
        engine = OpenAICompatibleEngine()
        engine.engine_id = normalized_engine_id
        return engine

    return DisabledEngine()

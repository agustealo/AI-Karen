from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORTEX_INTENT = REPO_ROOT / "src/ai_karen_engine/core/cortex/intent.py"
CORTEX_ROUTING = REPO_ROOT / "src/ai_karen_engine/core/cortex/routing_intents.py"
INTENT_PREDICTOR = (
    REPO_ROOT
    / "src/ai_karen_engine/core/intelligence/ml/predictors/intent.py"
)
INTELLIGENCE_RUNTIME = (
    REPO_ROOT / "src/ai_karen_engine/core/intelligence/intelligence_runtime.py"
)


def test_intelligence_intent_predictor_remains_signal_only() -> None:
    source = INTENT_PREDICTOR.read_text(encoding="utf-8")

    forbidden_execution_authority = (
        "provider_registry",
        "execute_plugin",
        "execute_tool",
        "ActionExecutionGate",
        "get_current_tenant",
        "select_provider",
    )
    for symbol in forbidden_execution_authority:
        assert symbol not in source


def test_public_classify_delegates_to_registered_prediction_runtime() -> None:
    source = INTELLIGENCE_RUNTIME.read_text(encoding="utf-8")
    classify_body = source.split("async def classify", 1)[1].split(
        "async def health", 1
    )[0]

    assert "self._ml_runtime.predict" in classify_body
    assert "PredictionTask(normalized_task)" in classify_body
    assert "semantic_encoding = await self._ml_runtime.encode" not in classify_body


def test_split_cortex_classifier_surfaces_are_explicit_debt_until_convergence() -> None:
    basic_source = CORTEX_INTENT.read_text(encoding="utf-8")
    routing_source = CORTEX_ROUTING.read_text(encoding="utf-8")

    assert "BASIC_INTENT_MAP" in basic_source
    assert "CAPABILITY_ROUTES" in routing_source
    assert "resolve_intent" in basic_source
    assert "resolve_capability_decision" in routing_source

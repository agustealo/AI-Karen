import pytest


@pytest.mark.cognitive
def test_all_engine_imports():
    imports = [
        "ai_karen_engine.core.reasoning.belief",
        "ai_karen_engine.core.reasoning.meta",
        "ai_karen_engine.core.adaptive.salience",
        "ai_karen_engine.core.adaptive.salience.decay",
        "ai_karen_engine.core.personalization.goals.lifecycle",
        "ai_karen_engine.core.personalization.goals.prioritization",
        "ai_karen_engine.core.personalization.goals.conflicts",
        "ai_karen_engine.core.personalization.preferences.resolver",
        "ai_karen_engine.core.personalization.preferences.lifecycle",
        "ai_karen_engine.core.personalization.snapshot",
        "ai_karen_engine.core.personalization.runtime",
        "ai_karen_engine.core.adaptive.learning.aggregates",
        "ai_karen_engine.core.memory.scoring.ranking",
    ]
    import importlib
    for mod in imports:
        try:
            importlib.import_module(mod)
        except Exception as e:
            pytest.fail(f"{mod} import failed: {type(e).__name__}: {e}")

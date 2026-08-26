from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"


def test_intelligence_ml_owns_performance_profile_implementation() -> None:
    canonical = CORE_ROOT / "intelligence" / "ml" / "performance_profiles.py"
    assert canonical.exists()
    source = canonical.read_text(encoding="utf-8")
    assert "class PerformanceProfileAggregator" in source
    assert "class AgentPerformanceProfile" in source
    assert "class CapabilityPerformanceProfile" in source
    assert "core.adaptive" not in source


def test_adaptive_evidence_aggregator_is_compatibility_only() -> None:
    source = (CORE_ROOT / "adaptive" / "learning" / "aggregates.py").read_text(
        encoding="utf-8"
    )
    assert "core.intelligence.ml.performance_profiles" in source
    assert "class EvidenceAggregator" not in source
    assert "_update_capability_profile" not in source
    assert "_update_agent_profile" not in source


def test_adaptive_profile_views_use_canonical_ml_profiles() -> None:
    for name in ("agent.py", "capability.py"):
        source = (CORE_ROOT / "adaptive" / "profiles" / name).read_text(
            encoding="utf-8"
        )
        assert "core.intelligence.ml.performance_profiles" in source
        assert "core.adaptive.contracts" not in source
        assert "core.adaptive.learning.aggregates" not in source


def test_adaptive_evaluation_is_canonical_ml_compatibility_only() -> None:
    source = (CORE_ROOT / "adaptive" / "evaluation" / "corpus.py").read_text(
        encoding="utf-8"
    )
    assert "CanonicalEvaluationCorpus" in source
    assert "core.intelligence.ml.evaluation" in source
    assert "expected_top_actions" not in source
    assert '"use_multi_agent"' not in source
    assert '"use_workflow"' not in source
    assert '"use_tool"' not in source


def test_adaptive_package_is_documented_as_transitional() -> None:
    source = (CORE_ROOT / "adaptive" / "__init__.py").read_text(encoding="utf-8")
    assert "Transitional compatibility package" in source
    assert "Do not add new execution or learning authority" in source

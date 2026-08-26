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


def test_adaptive_drift_is_quarantined_as_legacy_compatibility() -> None:
    package_source = (CORE_ROOT / "adaptive" / "drift" / "__init__.py").read_text(
        encoding="utf-8"
    )
    detector_source = (CORE_ROOT / "adaptive" / "drift" / "detector.py").read_text(
        encoding="utf-8"
    )
    assert "not a production drift authority" in package_source
    assert "core.intelligence.ml" in package_source
    assert "compatibility_only" in detector_source
    assert "self._threshold" not in detector_source
    assert "def _compress" not in detector_source


def test_intelligence_ml_owns_off_policy_evaluation() -> None:
    policy_root = CORE_ROOT / "intelligence" / "ml" / "policy_evaluation"
    contracts = (policy_root / "contracts.py").read_text(encoding="utf-8")
    estimators = (policy_root / "estimators.py").read_text(encoding="utf-8")
    promotion = (policy_root / "promotion.py").read_text(encoding="utf-8")
    assert "class PolicyObservation" in contracts
    assert "class IPSEstimator" in estimators
    assert "class SNIPSEstimator" in estimators
    assert "class DoublyRobustEstimator" in estimators
    assert "estimate.lower_bound < config.min_gain" in promotion
    assert "core.adaptive" not in contracts
    assert "core.adaptive" not in estimators
    assert "core.adaptive" not in promotion


def test_adaptive_policy_evaluation_modules_are_facades_only() -> None:
    policy_contracts = (
        CORE_ROOT / "adaptive" / "learning" / "policy_contracts.py"
    ).read_text(encoding="utf-8")
    estimators = (CORE_ROOT / "adaptive" / "learning" / "estimators.py").read_text(
        encoding="utf-8"
    )
    promotion = (CORE_ROOT / "adaptive" / "learning" / "promotion.py").read_text(
        encoding="utf-8"
    )
    canonical_import = "core.intelligence.ml.policy_evaluation"
    assert canonical_import in policy_contracts
    assert canonical_import in estimators
    assert canonical_import in promotion
    assert "class PolicyObservation" not in policy_contracts
    assert "class IPSEstimator" not in estimators
    assert "def evaluate_promotion" not in promotion


def test_adaptive_package_is_documented_as_transitional() -> None:
    source = (CORE_ROOT / "adaptive" / "__init__.py").read_text(encoding="utf-8")
    assert "Transitional compatibility package" in source
    assert "Do not add new execution or learning authority" in source

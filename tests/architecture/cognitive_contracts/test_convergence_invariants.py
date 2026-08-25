"""COG-CONVERGE-1 closure invariants."""

from __future__ import annotations

import ast
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path

from ai_karen_engine.core.cognitive.state import CognitiveState
from ai_karen_engine.core.contracts.cognitive import (
    BehaviorConfidence,
    EpistemicConfidence,
    LearningConfidence,
    MetaConfidence,
    ReasoningDepth,
    RetrievalConfidence,
    SalienceConfidence,
    VerificationRequirement,
)
from ai_karen_engine.core.contracts.compatibility import COGNITIVE_COMPATIBILITY_SHIMS
from ai_karen_engine.core.cortex.behavior import contracts as behavior_contracts
from ai_karen_engine.core.memory.contracts import ClaimStatus as MemoryClaimStatus
from ai_karen_engine.core.reasoning.belief.contracts import (
    ClaimStatus as BeliefClaimStatus,
    EvidenceType,
)
from ai_karen_engine.core.reasoning.meta import contracts as meta_contracts

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def test_one_reasoning_depth_authority() -> None:
    assert behavior_contracts.VerificationDepth is ReasoningDepth
    assert meta_contracts.ReasoningDepth is ReasoningDepth


def test_one_verification_contract() -> None:
    assert behavior_contracts.VerificationRequirement is VerificationRequirement
    assert meta_contracts.VerificationNeedAssessment is VerificationRequirement


def test_one_claim_status_authority() -> None:
    assert BeliefClaimStatus is MemoryClaimStatus


def test_cognitive_state_exists_and_requires_explicit_tenant() -> None:
    names = {field.name for field in fields(CognitiveState)}
    assert {"tenant_id", "belief", "goals", "salience", "context", "meta", "adaptive", "policy"} <= names
    try:
        CognitiveState(state_id="s", request_id="r", correlation_id="c", tenant_id="default")
    except ValueError:
        pass
    else:
        raise AssertionError("CognitiveState must reject implicit/default tenant scope")


def test_public_behavior_boundary_has_no_loose_cognitive_dicts() -> None:
    annotations = behavior_contracts.BehaviorSelectionContext.__annotations__
    forbidden = {
        "belief_assessment",
        "goal_state",
        "context_plan",
        "memory_signals",
        "user_model",
        "relationship_context",
        "adaptive_recommendations",
        "reasoning_assessment",
        "policy_constraints",
    }
    assert forbidden.isdisjoint(annotations)
    assert annotations.get("metadata") is not None


def test_confidence_domains_are_distinct_types() -> None:
    domains = {
        EpistemicConfidence,
        RetrievalConfidence,
        SalienceConfidence,
        BehaviorConfidence,
        MetaConfidence,
        LearningConfidence,
    }
    assert len(domains) == 6
    for domain in domains:
        assert float(domain(0.6)) == 0.6


def test_temporal_cognitive_state_uses_datetime() -> None:
    created = CognitiveState.__annotations__["created_at"]
    assert created is datetime


def test_legacy_goal_and_evidence_types_have_sunsets() -> None:
    mapping = {shim.legacy_symbol: shim for shim in COGNITIVE_COMPATIBILITY_SHIMS}
    goal = "ai_karen_engine.core.personalization.contracts.UserGoalStatus"
    evidence = "ai_karen_engine.core.personalization.goals.contracts.EvidenceSourceType"
    assert mapping[goal].canonical_symbol.endswith("personalization.goals.contracts.GoalState")
    assert mapping[evidence].canonical_symbol.endswith("reasoning.belief.contracts.EvidenceType")
    assert mapping[goal].remove_after > date(2026, 8, 25)
    assert mapping[evidence].remove_after > date(2026, 8, 25)
    assert len(EvidenceType) >= 1


def test_no_expired_cognitive_shims() -> None:
    expired = [shim for shim in COGNITIVE_COMPATIBILITY_SHIMS if shim.remove_after < date.today()]
    assert not expired, f"expired cognitive compatibility shims: {expired}"


def test_pure_cognitive_kernel_does_not_import_provider_or_platform_authority() -> None:
    roots = [
        CORE / "cognitive",
        CORE / "contracts",
        CORE / "cortex" / "behavior",
        CORE / "reasoning" / "belief",
        CORE / "reasoning" / "meta",
        CORE / "adaptive" / "salience",
        CORE / "adaptive" / "learning" / "experience",
        CORE / "personalization" / "goals",
        CORE / "context",
    ]
    forbidden_prefixes = (
        "ai_karen_engine.platform",
        "ai_karen_engine.providers",
        "ai_karen_engine.extensions",
        "fastapi",
        "sqlalchemy",
        "redis",
        "openai",
        "ollama",
        "vllm",
        "httpx",
        "requests",
    )
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name.startswith(forbidden_prefixes):
                        hits.append(f"{path.relative_to(CORE)} -> {name}")
    assert not hits, "provider/platform authority leaked into pure cognitive kernel:\n" + "\n".join(hits)

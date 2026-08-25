from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_karen_engine.core.contracts.cognitive import (
    BeliefSnapshot,
    CognitiveScope,
    CognitiveState,
    GoalSnapshot,
    PolicySnapshot,
    ReasoningDepth,
    SalienceSnapshot,
    VerificationRequirement,
)
from ai_karen_engine.core.cortex.behavior.contracts import (
    BehaviorSelectionContext,
    VerificationDepth,
)
from ai_karen_engine.core.memory.contracts import ClaimStatus as MemoryClaimStatus
from ai_karen_engine.core.personalization.goals.contracts import (
    EvidenceSourceType,
    GoalState,
)
from ai_karen_engine.core.reasoning.belief.contracts import (
    ClaimStatus as BeliefClaimStatus,
    EvidenceType,
)
from ai_karen_engine.core.reasoning.meta.contracts import (
    ReasoningDepth as MetaReasoningDepth,
    VerificationNeedAssessment,
)


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def test_one_reasoning_depth_authority() -> None:
    assert VerificationDepth is ReasoningDepth
    assert MetaReasoningDepth is ReasoningDepth


def test_one_verification_contract() -> None:
    assert VerificationNeedAssessment is VerificationRequirement


def test_one_claim_status_authority() -> None:
    assert BeliefClaimStatus is MemoryClaimStatus
    assert MemoryClaimStatus.UNKNOWN.value == "unknown"
    assert MemoryClaimStatus.CONTRADICTED.value == "contradicted"


def test_one_evidence_type_authority() -> None:
    assert EvidenceSourceType is EvidenceType


def test_goal_state_authority_is_goals_domain() -> None:
    import ai_karen_engine.core.personalization.contracts as personalization_contracts

    assert not hasattr(personalization_contracts, "GoalState")
    assert GoalState.ACTIVE.value == "active"
    assert GoalState.SATISFIED.value == "satisfied"


def test_cognitive_scope_requires_explicit_tenant() -> None:
    with pytest.raises(ValueError):
        CognitiveScope(tenant_id="default")
    with pytest.raises(ValueError):
        CognitiveScope(tenant_id="")
    scope = CognitiveScope(tenant_id="tenant-test", user_id="user-test")
    assert scope.tenant_id == "tenant-test"


def test_cognitive_state_exists_and_is_typed() -> None:
    state = CognitiveState(
        request_id="request-1",
        correlation_id="correlation-1",
        scope=CognitiveScope(tenant_id="tenant-test", user_id="user-test"),
    )
    assert isinstance(state.beliefs, BeliefSnapshot)
    assert isinstance(state.goals, GoalSnapshot)
    assert isinstance(state.salience, SalienceSnapshot)
    assert isinstance(state.policy, PolicySnapshot)


def test_behavior_context_coerces_legacy_maps_to_typed_snapshots() -> None:
    context = BehaviorSelectionContext(
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="tenant-test",
        belief_assessment={"confidence": 0.75},
        goal_state={"active_goals": ["goal-1"]},
        salience={"overall": 0.8, "activation": 0.7},
        policy_constraints={"blocked_behaviors": ["delegate"], "risk": 0.2},
    )
    assert isinstance(context.belief_assessment, BeliefSnapshot)
    assert context.belief_assessment.epistemic_confidence == pytest.approx(0.75)
    assert isinstance(context.goal_state, GoalSnapshot)
    assert context.goal_state.active_goal_ids == ("goal-1",)
    assert isinstance(context.salience, SalienceSnapshot)
    assert isinstance(context.policy_constraints, PolicySnapshot)


def test_behavior_context_rejects_ambiguous_default_tenant() -> None:
    with pytest.raises(ValueError):
        BehaviorSelectionContext(
            request_id="request-1",
            correlation_id="correlation-1",
            tenant_id="default",
        )


def test_canonical_cognitive_contracts_do_not_import_execution_or_platform() -> None:
    files = [
        CORE / "contracts" / "cognitive.py",
        CORE / "cortex" / "behavior" / "contracts.py",
        CORE / "reasoning" / "contracts.py",
        CORE / "reasoning" / "belief" / "contracts.py",
        CORE / "reasoning" / "meta" / "contracts.py",
        CORE / "memory" / "contracts.py",
        CORE / "personalization" / "goals" / "contracts.py",
    ]
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "openai",
        "ollama",
        "vllm",
        "httpx",
        "requests",
        "ai_karen_engine.platform",
        "ai_karen_engine.providers",
        "ai_karen_engine.extensions",
        "ai_karen_engine.api_routes",
    )

    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module.startswith(forbidden_prefixes):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert not violations, "\n".join(violations)


def test_canonical_contract_files_define_no_duplicate_cross_domain_classes() -> None:
    expected_single_owner = {
        "ReasoningDepth": CORE / "contracts" / "cognitive.py",
        "VerificationRequirement": CORE / "contracts" / "cognitive.py",
        "ClaimStatus": CORE / "memory" / "contracts.py",
        "EvidenceType": CORE / "reasoning" / "belief" / "contracts.py",
        "GoalState": CORE / "personalization" / "goals" / "contracts.py",
    }
    scan_roots = [
        CORE / "contracts",
        CORE / "cortex",
        CORE / "memory",
        CORE / "personalization",
        CORE / "reasoning",
    ]

    found: dict[str, list[Path]] = {name: [] for name in expected_single_owner}
    for root in scan_roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef)):
                    if isinstance(node, ast.ClassDef) and node.name in found:
                        found[node.name].append(path)

    for name, expected_owner in expected_single_owner.items():
        assert found[name] == [expected_owner], (
            f"{name} must have exactly one class definition in {expected_owner}; "
            f"found={found[name]}"
        )

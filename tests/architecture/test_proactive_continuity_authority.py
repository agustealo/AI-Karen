from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_proactive_continuity_is_intelligence_owned() -> None:
    service = _text(
        "src/ai_karen_engine/core/intelligence/proactive/service.py"
    )
    contracts = _text(
        "src/ai_karen_engine/core/intelligence/proactive/contracts.py"
    )

    assert "class ProactiveContinuityService" in service
    assert "class ProactiveContinuityRepository(ABC)" in contracts
    assert "core.adaptive" not in service
    assert "core.adaptive" not in contracts


def test_runtime_authorizes_continuity_through_context_pipeline() -> None:
    stages = _text("src/ai_karen_engine/core/cortex/context_stages.py")
    resolver = _text("src/ai_karen_engine/core/runtime/evidence_resolver.py")

    assert "source=EvidenceSource.USER_MODEL" in stages
    assert 'capability="memory.read"' in stages
    assert "requirement.source is EvidenceSource.USER_MODEL" in resolver
    assert "ProactiveContinuityService" in resolver
    assert "PostgresProactiveContinuityRepository" in resolver


def test_continuity_never_claims_execution_authority() -> None:
    service = _text(
        "src/ai_karen_engine/core/intelligence/proactive/service.py"
    )
    prompt = _text(
        "src/ai_karen_engine/core/runtime/prompt/prompt_assembler.py"
    )

    assert '"execution_authorized": False' in service
    assert '"execution_authorized": False' in prompt
    assert "possible next need" in prompt
    assert "not as a user fact, command, permission, or completed action" in prompt


def test_proactive_candidates_are_preserved_for_outcome_learning() -> None:
    runtime = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")

    assert '"continuity_candidate_ids"' in runtime
    assert '"continuity_source_types"' in runtime
    assert '"continuity_count"' in runtime


def test_graph_workflows_receive_same_proactive_context() -> None:
    runtime = _text("src/ai_karen_engine/core/runtime/chat_runtime.py")
    workflow = _text("src/ai_karen_engine/core/runtime/workflow_runtime.py")

    assert 'request.metadata["proactive_continuity"]' in runtime
    assert "request_config.update(request.metadata or {})" in workflow


def test_obsolete_adaptive_suggestion_authority_is_removed() -> None:
    suggestion_root = CORE / "adaptive" / "suggestions"

    assert not suggestion_root.exists()
    assert not (ROOT / "tests/core/adaptive/test_suggestions.py").exists()


def test_fake_planning_api_is_removed_and_not_mounted() -> None:
    planning = ROOT / "src/ai_karen_engine/api_routes/cognition/planning.py"
    routers = _text("src/ai_karen_engine/server/routers.py")

    assert not planning.exists()
    assert "api_routes.cognition.planning" not in routers
    assert "planning_router" not in routers


def test_proactive_repository_reads_only_current_governed_evidence() -> None:
    repository = _text(
        "src/ai_karen_engine/platform/personalization/proactive_repository.py"
    )

    assert "JOIN public.memory_event me" in repository
    assert "me.consent_state = 'granted'" in repository
    assert "me.valid_to IS NULL OR me.valid_to > :now" in repository
    assert "personalization_behavior_pattern" in repository
    assert "async_transaction_scope(tenant_id=tenant)" in repository
